from functools import partial
import logging

from qcodes.instrument_drivers.devices import VoltageDivider
from qcodes.utils.validators import Numbers

from qcodes.instrument.parameter import ManualParameter
from qcodes.utils.validators import Enum

from configparser import ConfigParser


log = logging.getLogger(__name__)

class ConfigFile:
    """
    Object to be used for interacting with the config file.
    Currently the config file MUST have the name 'sample.config'

    The ConfigFile is constantly synced with the config file on disk
    (provided that only this object was used to change the file)
    """

    def __init__(self):
        self._filename = 'modules/Majorana/sample.config'
        self._cfg = ConfigParser()
        self._load()

    def _load(self):
        self._cfg.read(self._filename)

    def reload(self):
        self._load()

    def get(self, section, field=None):
        """
        Gets the value of the specified section/field.
        If no field is specified, the entire section is returned
        as a dict.

        Example: ConfigFile.get('QDac Channel Labels', '2')
        """
        # Try to be really clever about the input
        if not isinstance(field, str) and (field is not None):
            field = '{}'.format(field)

        if field is None:
            output = dict(zip(self._cfg[section].keys(),
                              self._cfg[section].values()))
        else:
            output = self._cfg[section][field]

        return output

    def set(self, section, field, value):
        """
        Set a value in the config file.
        Immediately writes to disk.
        """
        if not isinstance(value, str):
            value = '{}'.format(value)

        self._cfg[section][field] = value

        with open(self._filename, 'w') as configfile:
            self._cfg.write(configfile)


##################################################
# References to config files

configs = ConfigFile()


def bias_channels():
    """
    A convenience function returning a list of bias channels.
    """
    bias_chan1 = configs.get('Channel Parameters', 'topo bias channel')
    bias_chan2 = configs.get('Channel Parameters', 'left sensor bias channel')
    bias_chan3 = configs.get('Channel Parameters', 'right sensor bias channel')

    return [int(bias_chan1), int(bias_chan2), int(bias_chan3)]


def used_channels():
    """
    Return a list of currently labelled channels as ints.
    """
    l_chs = configs.get('QDac Channel Labels')
    return sorted([int(key) for key in l_chs.keys()])


def used_voltage_params():
    """
    Returns a list of qdac voltage parameters for the used channels
    """
    chans = sorted(used_channels())
    voltages = [qdac.parameters['ch{:02}_v'.format(ii)] for ii in chans]

    return voltages


def channel_labels():
    """
    Returns a dict of the labelled channels. Key: channel number (int),
    value: label (str)
    """
    labs = configs.get('QDac Channel Labels')
    output = dict(zip([int(key) for key in labs.keys()], labs.values()))

    return output

def print_voltages_all():
    parnames = sorted([par for par in qdac.parameters.keys() if par.endswith('_v')])
    for parname in parnames:
        print('{}: {} V'.format(parname, qdac.parameters[parname].get()))
        
    check_unused_qdac_channels()


def qdac_slopes():
    """
    Returns a dict with the QDac slopes defined in the config file
    """
    qdac_slope = float(configs.get('Ramp speeds',
                                   'max rampspeed qdac'))
    bg_slope = float(configs.get('Ramp speeds',
                                 'max rampspeed bg'))
    bias_slope = float(configs.get('Ramp speeds',
                                   'max rampspeed bias'))

    QDAC_SLOPES = dict(zip(used_channels(),
                           len(used_channels())*[qdac_slope]))

    QDAC_SLOPES[int(configs.get('Channel Parameters',
                                'backgate channel'))] = bias_slope
    for ii in bias_channels():
        QDAC_SLOPES[ii] = bias_slope

    return QDAC_SLOPES

def check_unused_qdac_channels():
    qdac._get_status()
    for ch in [el for i, el in enumerate(range(1,48)) if el not in used_channels()]:
        temp_v = qdac.parameters['ch{:02}_v'.format(ch)].get_latest()
        if temp_v > 0.0:
            log.warning('Unused qDac channel not zero: channel {:02}: {}'.format(ch, temp_v))

check_unused_qdac_channels()
##################################################
# Initialise IV converters, voltage dividers, etc.

IV_CONV_GAIN_TOPO = ManualParameter('IVgain topo bias',
                                    unit='V/A',
                                    vals=Enum(1e5, 1e6, 1e7, 1e8, 1e9))
IV_CONV_GAIN_TOPO(float(configs.get('Gain settings', 'iv topo gain')))

IV_CONV_GAIN_R = ManualParameter('IVgain sens right',
                                 unit='V/A',
                                 vals=Enum(1e5, 1e6, 1e7, 1e8, 1e9))
IV_CONV_GAIN_R(float(configs.get('Gain settings', 'iv right gain')))

IV_CONV_GAIN_L = ManualParameter('IVgain sens left',
                                 unit='V/A',
                                 vals=Enum(1e5, 1e6, 1e7, 1e8, 1e9))
IV_CONV_GAIN_L(float(configs.get('Gain settings', 'iv left gain')))


AC_EXCITATION_TOPO = VoltageDivider(lockin_topo.amplitude,
                                    float(configs.get('Gain settings',
                                                'ac factor topo')))
AC_EXCITATION_R = VoltageDivider(lockin_right.amplitude,
                                 float(configs.get('Gain settings',
                                             'ac factor right')))
AC_EXCITATION_L = VoltageDivider(lockin_left.amplitude,
                                  float(configs.get('Gain settings',
                                             'ac factor left')))


##################################################
# The QDAC dict exposed to the user. This dict contains a mapping from
# channel number to QCoDeS object whose 'get' method returns the voltage
# AT SAMPLE (attenuation not taken into account yet) from that channel

# first initialise it with the 'raw' voltages
QDAC = dict(zip(used_channels(), used_voltage_params()))

# User defined special channels with special names exposed to the user
topo_bias = VoltageDivider(QDAC[int(configs.get('Channel Parameters',
                                                'topo bias channel'))],
                           float(configs.get('Gain settings',
                                             'dc factor topo')))
sens_r_bias = VoltageDivider(QDAC[int(configs.get('Channel Parameters',
                                                  'right sensor bias channel'))],
                             float(configs.get('Gain settings',
                                               'dc factor right')))
sens_l_bias = VoltageDivider(QDAC[int(configs.get('Channel Parameters',
                                                  'left sensor bias channel'))],
                             float(configs.get('Gain settings',
                                               'dc factor left')))
# update the QDAC dict with these as well
QDAC[int(configs.get('Channel Parameters', 'topo bias channel'))] = topo_bias
QDAC[int(configs.get('Channel Parameters', 'left sensor bias channel'))] = sens_l_bias
QDAC[int(configs.get('Channel Parameters', 'right sensor bias channel'))] = sens_r_bias

# now overwrite the channel labels
for ch in used_channels():
    QDAC[ch].label = channel_labels()[ch]


# A dictionary with max ramp speed for qDac channels.
# Bias channels, backgate and cutters/plungers have their own values
QDAC_SLOPES = qdac_slopes()

# Adding a parameter for conductance measurement
def get_conductance(lockin, ac_excitation, iv_conv):
    """
    get_cmd for conductance parameter
    """
    resistance_quantum = 25.818e3  # [Ohm]
    i = lockin.X() / iv_conv
    # ac excitation voltage at the sample
    v_sample = ac_excitation()
    return (i/v_sample)*resistance_quantum


# Delete conductance parameters, if they are already defined
try:
    del lockin_topo.parameters['g']
except KeyError:
    pass

try:
    del lockin_right.parameters['g']
except KeyError:
    pass

try:
    del lockin_left.parameters['g']
except KeyError:
    pass


lockin_topo.add_parameter(name='g',
                          label='Topo g (e^2/h)',
                          unit='',
                          get_cmd=partial(get_conductance,
                                          lockin_topo, AC_EXCITATION_TOPO,
                                          float(configs.get('Gain settings',
                                                            'iv topo gain'))),
                          set_cmd=None)

lockin_right.add_parameter(name='g',
                           label='Sensor right g (e^2/h)',
                           unit='',
                           get_cmd=partial(get_conductance,
                                           lockin_right, AC_EXCITATION_R,
                                           float(configs.get('Gain settings',
                                                             'iv right gain'))),
                           set_cmd=None)

lockin_left.add_parameter(name='g',
                          label='Sensor left g (e^2/h)',
                          unit='',
                          get_cmd=partial(get_conductance,
                                          lockin_left, AC_EXCITATION_L,
                                          float(configs.get('Gain settings',
                                                            'iv left gain'))),
                          set_cmd=None)


def set_ranges(qdac_channel_dictionary):
    """
    Set ranges to channels if:
    - channels range are defined
    - in the config file and if the channel is in use.

    Args:
      -qdac_channel_dictionary: dict of chan_id:chan parameter
    """
    ranges = configs.get('Channel ranges')
    for chan_id in qdac_channel_dictionary:
        try:
            chan_range = ranges[str(chan_id)]
        except KeyError:
            log.debug("No range defined for chan %s. Using default.", chan_id)
            continue

        minmax = chan_range.split(" ")
        if len(minmax) != 2:
            raise ValueError("Expected: min max. Got {}".format(chan_range))
        else:
            rangemin = float(minmax[0])
            rangemax = float(minmax[1])
        channel = qdac_channel_dictionary[chan_id]
        if isinstance(channel, VoltageDivider):
            # set the validator on the underlying qdac channel
            channel.v1.set_validator(Numbers(rangemin, rangemax))
        else:
            channel.set_validator(Numbers(rangemin, rangemax))

set_ranges(QDAC)