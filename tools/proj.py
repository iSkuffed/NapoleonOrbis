"""World projection (RoadMap D2): identity on the vanilla nap_europe theatre, piecewise-linear plate carree outside.

Inside the vanilla theatre (-410,-190)..(340,195), i.e. lon -12.87..44.21, lat 34.21..63.74, positions equal vanilla
(x = 13.14*lon - 240.9, y = 13.04*lat - 636.1, research/00), so all vanilla Europe data is reused unchanged. Outside,
each axis is linear again up to the theatre edge: about 9.6 u/deg west (Americas), 10.7 u/deg east (Asia), 10.15 u/deg
north/south. Seam at 169 W, between the Diomedes, keeping Alaska and Chukotka whole.

  python tools/proj.py        # self-check
"""
import numpy as np

VAN_SX, VAN_X0, VAN_SY, VAN_Y0 = 13.14, -240.9, 13.04, -636.1
VT_MIN, VT_MAX = (-410, -190), (340, 195)            # vanilla theatre
# world theatre: x +-1910 (G3); y chosen so 2-unit pathfinding cells and 75-unit sea-grid cells stay aligned with vanilla
THEATRE_MIN, THEATRE_MAX = (-1910, -1240), (1910, 365)
BOX_MIN, BOX_MAX = (-1920, -1280), (1920, 1280)     # regions/terrain world box, centred (G2)
SEAM = -169.0
LAT_K = 10.15                                        # u/deg outside the vanilla band, north and south

LON_W, LON_E = (VT_MIN[0] - VAN_X0) / VAN_SX, (VT_MAX[0] - VAN_X0) / VAN_SX
LAT_S, LAT_N = (VT_MIN[1] - VAN_Y0) / VAN_SY, (VT_MAX[1] - VAN_Y0) / VAN_SY
KX_W = (VT_MIN[0] - THEATRE_MIN[0]) / (LON_W - SEAM)
KX_E = (THEATRE_MAX[0] - VT_MAX[0]) / (SEAM + 360 - LON_E)


def to_world(lon, lat, wrap=True):
    """lon, lat (degrees, arrays ok) -> world x, y. wrap=False: lon already in [SEAM, SEAM + 360] (seam-cut
    geometry), so edge vertices stay on their own side instead of wrapping across the map."""
    L = (np.asarray(lon, float) - SEAM) % 360 + SEAM if wrap else np.asarray(lon, float)
    lat = np.asarray(lat, float)
    x = np.where(L < LON_W, VT_MIN[0] - (LON_W - L) * KX_W,
                 np.where(L > LON_E, VT_MAX[0] + (L - LON_E) * KX_E, VAN_SX * L + VAN_X0))
    y = np.where(lat < LAT_S, VT_MIN[1] - (LAT_S - lat) * LAT_K,
                 np.where(lat > LAT_N, VT_MAX[1] + (lat - LAT_N) * LAT_K, VAN_SY * lat + VAN_Y0))
    return x, y


def to_lonlat(x, y):
    """Inverse of to_world (lon in [-180, 180))."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    L = np.where(x < VT_MIN[0], LON_W - (VT_MIN[0] - x) / KX_W,
                 np.where(x > VT_MAX[0], LON_E + (x - VT_MAX[0]) / KX_E, (x - VAN_X0) / VAN_SX))
    lat = np.where(y < VT_MIN[1], LAT_S - (VT_MIN[1] - y) / LAT_K,
                   np.where(y > VT_MAX[1], LAT_N + (y - VT_MAX[1]) / LAT_K, (y - VAN_Y0) / VAN_SY))
    return (L + 180) % 360 - 180, lat


def _selfcheck():
    # vanilla theatre corners map onto themselves; seam edges onto the theatre edge
    x, y = to_world([LON_W, LON_E, SEAM, SEAM + 359.999999], [LAT_S, LAT_N, LAT_S, LAT_N])
    assert np.allclose(x, [-410, 340, -1910, 1910], atol=1e-3) and np.allclose(y, [-190, 195, -190, 195]), (x, y)
    # Paris and Moscow are vanilla positions; Diomedes fall on opposite map edges
    px, py = to_world([2.35, 37.62], [48.86, 55.75])
    assert np.allclose(px, [13.14 * 2.35 - 240.9, 13.14 * 37.62 - 240.9]) and np.allclose(py[0], 13.04 * 48.86 - 636.1)
    dx, _ = to_world([-168.9, -169.05], [65.8, 65.8])
    assert dx[0] < -1900 and dx[1] > 1900, dx
    lon = np.random.default_rng(0).uniform(-180, 180, 1000); lat = np.random.default_rng(1).uniform(-70, 80, 1000)
    lo, la = to_lonlat(*to_world(lon, lat))
    assert np.allclose((lo - lon + 180) % 360 - 180, 0, atol=1e-9) and np.allclose(la, lat)
    x, y = to_world(lon, lat)
    assert (x >= THEATRE_MIN[0]).all() and (x < THEATRE_MAX[0]).all()
    _, ys = to_world(0, [-58, 80])
    assert THEATRE_MIN[1] <= ys[0] and ys[1] <= THEATRE_MAX[1], ys
    assert (VT_MIN[0] - THEATRE_MIN[0]) % 75 == 0 and (VT_MIN[1] - THEATRE_MIN[1]) % 150 == 0
    print(f'proj ok: x {KX_W:.2f} u/deg W, {KX_E:.2f} E; y {LAT_K} N/S; lat -58 -> {ys[0]:.0f}, 80 -> {ys[1]:.0f}')


if __name__ == '__main__':
    _selfcheck()
