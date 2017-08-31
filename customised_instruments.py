# -*- coding: utf-8 -*-
"""
Customised instruments with extra features such as voltage dividers and derived
parameters for use with T3
"""
import numpy as np

from qcodes.instrument_drivers.QDev.QDac_channels import QDac
from qcodes.instrument_drivers.stanford_research.SR830 import SR830
from qcodes.instrument_drivers.stanford_research.SR830 import ChannelBuffer
from qcodes.instrument_drivers.Keysight.Keysight_34465A import Keysight_34465A
from qcodes.instrument_drivers.devices import VoltageDivider
from qcodes.instrument_drivers.Harvard.Decadac import Decadac

from qcodes import ArrayParameter

class Scope_avg(ArrayParameter):

    def __init__(self, name, channel=1, **kwargs):

        super().__init__(name, shape=(1,), **kwargs)
        self.has_setpoints = False
        self.zi = self._instrument

        if not channel in [1, 2]:
            raise ValueError('Channel must be 1 or 2')

        self.channel = channel

    def make_setpoints(self, sp_start, sp_stop, sp_npts):
        """
        Makes setpoints and prepares the averager (updates its unit)
        """
        self.shape = (sp_npts,)
        self.unit = self._instrument.Scope.units[self.channel-1]
        self.setpoints = (tuple(np.linspace(sp_start, sp_stop, sp_npts)),)
        self.has_setpoints = True

    def get(self):

        if not self.has_setpoints:
            raise ValueError('Setpoints not made. Run make_setpoints')

        data = self._instrument.Scope.get()[self.channel-1]
        data_avg = np.mean(data, 0)

        # KDP: handle less than 4096 points
        # (4096 needs to be multiple of number of points)
        down_samp = np.int(self._instrument.scope_length.get()/self.shape[0])
        if down_samp > 1:
            data_ret = data_avg[::down_samp]
        else:
            data_ret = data_avg

        return data_ret

# A conductance buffer, needed for the faster 2D conductance measurements
# (Dave Wecker style)
class ConductanceBuffer(ChannelBuffer):
    """
    A full-buffered version of the conductance based on an
    array of X measurements

    We basically just slightly tweak the get method
    """

    def __init__(self, name: str, instrument: 'SR830_T10', **kwargs):
        super().__init__(name, instrument, channel=1)
        self.unit = ('e^2/h')

    def get(self):
        # If X is not being measured, complain
        if self._instrument.ch1_display() != 'X':
            raise ValueError('Can not return conductance since X is not '
                             'being measured on channel 1.')

        resistance_quantum = 25.818e3  # (Ohm)
        xarray = super().get()
        iv_conv = self._instrument.ivgain
        ac_excitation = self._instrument.amplitude_true()

        gs = xarray/iv_conv/ac_excitation*resistance_quantum

        return gs

# Subclass the SR830

class SR830_T3(SR830):
    """
    An SR830 with the following super powers:
        - a Voltage divider
        - An I/V converter
        - A conductance buffer
    """

    def __init__(self, name, address, config, **kwargs):
        super().__init__(name, address, **kwargs)

        # using the vocabulary of the config file
        self.ivgain = float(config.get('Gain settings',
                                      'iv gain'))
        self.__acf = 1

        self.add_parameter('amplitude_true',
                           label='ac bias',
                           parameter_class=VoltageDivider,
                           v1=self.amplitude,
                           division_value=self.acfactor)
        
        self.acbias = self.amplitude_true

        self.add_parameter('g',
                           label='{} conductance'.format(self.name),
                           # use lambda for late binding
                           get_cmd=self._get_conductance,
                           unit='e^2/h',
                           get_parser=float)

        self.add_parameter('conductance',
                           label='{} conductance'.format(self.name),
                           parameter_class=ConductanceBuffer)
        
        self.add_parameter('resistance',
                           label='{} Resistance'.format(self.name),
                           get_cmd=self._get_resistance,
                           unit='Ohm',
                           get_parser=float)

    def _get_conductance(self):
        """
        get_cmd for conductance parameter
        """
        resistance_quantum = 25.8125e3  # (Ohm)
        i = self.R() / self.ivgain
        # ac excitation voltage at the sample
        v_sample = self.amplitude_true()

        return (i/v_sample)*resistance_quantum

    def _get_resistance(self):
        """
        get_cmd for resistance parameter
        """
        i = self.R() / self.ivgain
        # ac excitation voltage at the sample
        v_sample = self.amplitude_true()

        return (v_sample/i)
    
    @property
    def acfactor(self):
        return self.__acf

    @acfactor.setter
    def acfactor(self, acfactor):
        self.__acf = acfactor
        self.amplitude_true.division_value = acfactor

    def snapshot_base(self, update=False, params_to_skip_update=None):
        if params_to_skip_update is None:
            params_to_skip_update = ('conductance', 'ch1_databuffer', 'ch2_databuffer')
        snap = super().snapshot_base(update=update,
                                     params_to_skip_update=params_to_skip_update)
        return snap

# Subclass the QDAC


class QDAC_T10(QDac):
    """
    A QDac with three voltage dividers
    """
    def __init__(self, name, address, config, **kwargs):
        super().__init__(name, address, **kwargs)

        # Define the named channels

        topo_channel = int(config.get('Channel Parameters',
                                      'topo bias channel'))
        topo_channel = self.channels[topo_channel-1].v

        self.add_parameter('current_bias',
                           label='{} conductance'.format(self.name),
                           # use lambda for late binding
                           get_cmd=lambda: self.channels.chan40.v.get()/10E6*1E9,
                           set_cmd=lambda value: self.channels.chan40.v.set(value*1E-9*10E6),
                           unit='nA',
                           get_parser=float)

        self.topo_bias = VoltageDivider(topo_channel,
                                        float(config.get('Gain settings',
                                                         'dc factor topo')))
        
        
class Decadac_T3(Decadac):
    """
    A Decadac with one voltage dividers
    """
    def __init__(self, name, address, config, **kwargs):
        super().__init__(name, address, **kwargs)

        # Define the named channels
        
        self.config = config
        
        # Assign labels:
        labels = config.get('Decadac Channel Labels')
        for chan, label in labels.items():
            self.channels[int(chan)].volt.label = label

        # Take voltage divider of source/drain into account:
        dcbias_i = int(config.get('Channel Parameters',
                                      'source channel'))
        dcbias = self.channels[dcbias_i].volt
        self.dcbias = VoltageDivider(dcbias,
                                        float(config.get('Gain settings',
                                                         'dc factor')))
        self.dcbias.label = config.get('Decadac Channel Labels', dcbias_i)
        
        # Assign custom variable names
        lcut = int(config.get('Channel Parameters', 'left cutter'))
        self.lcut = self.channels[lcut].volt    
        
        rcut = int(config.get('Channel Parameters', 'right cutter'))
        self.rcut = self.channels[rcut].volt
        
        jj = int(config.get('Channel Parameters', 'central cutter'))
        self.jj = self.channels[jj].volt
        
        rplg = int(config.get('Channel Parameters', 'right plunger'))
        self.rplg = self.channels[rplg].volt
        
        lplg = int(config.get('Channel Parameters', 'left plunger'))
        self.lplg = self.channels[lplg].volt
        
        
        self.add_parameter('cutters',
                           label='{} cutters'.format(self.name),
                           # use lambda for late binding
                           get_cmd=self.get_cutters,
                           set_cmd=self.set_cutters,
                           unit='V',
                           get_parser=float)


    def set_all(self, voltage_value, set_dcbias=False):
        channels_in_use = self.config.get('Decadac Channel Labels').keys()
        channels_in_use = [int(ch) for ch in channels_in_use]
            
        for ch in channels_in_use:
            self.channels[ch].volt.set(voltage_value)
            
        if set_dcbias:
            self.dcbias.set(voltage_value)

    def set_cutters(self, voltage_value):
        dic = self.config.get('Channel Parameters')
            
        self.channels[int(dic['left cutter'])].volt.set(voltage_value)
        self.channels[int(dic['right cutter'])].volt.set(voltage_value)
        
    def get_cutters(self):
        dic = self.config.get('Channel Parameters')
            
        vleft = self.channels[int(dic['left cutter'])].volt.get()
        vright = self.channels[int(dic['right cutter'])].volt.get()
        if (abs(vleft-vright)>0.05):
            print('Error! Left and right cutter are not the same!')
        else:
            return vleft
        
        
# Subclass the DMM


class Keysight_34465A_T10(Keysight_34465A):
    """
    A Keysight DMM with an added I-V converter
    """
    def __init__(self, name, address, **kwargs):
        super().__init__(name, address, **kwargs)

        self.iv_conv = 1

        self.add_parameter('ivconv',
                           label='Current',
                           unit='pA',
                           get_cmd=self._get_current,
                           set_cmd=None)

    def _get_current(self):
        """
        get_cmd for dmm readout of IV_TAMP parameter
        """
        return self.volt()/self.iv_conv*1E12

