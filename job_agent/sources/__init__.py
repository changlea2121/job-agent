from .greenhouse import GreenhouseAdapter
from .kpn import KpnAdapter
from .workday import WorkdayAdapter

ADAPTERS = {
    "greenhouse": GreenhouseAdapter,
    "workday": WorkdayAdapter,
    "kpn": KpnAdapter,
}
