import warnings


warnings.warn(
    "Package 'v2simux' is deprecated and has been merged into 'v2sim'. "
    "Please use 'v2sim' instead.",
    DeprecationWarning,
    stacklevel=2
)

from .locale import *
from .traffic import *
from .trafficgen import *
from .plotkit import *
from .plugins import *
from .statistics import *
from .sim_core import (
    get_internal_components,
    load_external_components,
    get_sim_params,
    simulate_multi,
    simulate_single,
    V2SimInstance,
    MsgPack,
    PLUGINS_FILE,
    RESULTS_FOLDER,
    TRIP_EVENT_LOG,
    SIM_INFO_LOG,
    PLUGINS_DIR,
)

__version__ = "1.3.3"