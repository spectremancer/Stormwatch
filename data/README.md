# Offline map outlines

`world_land.geojson` contains Natural Earth's public-domain 1:110m land
polygons for the whole world, including all continents and Antarctica.
It is bundled for offline geographic context, not precise boundaries/navigation.

Source: https://github.com/nvkelso/natural-earth-vector/blob/master/geojson/ne_110m_land.geojson
SHA-256: `9e0729ee253ca7d7a5c4ae9395fb1902264c5377c52e224d13dd85010e2835d9`
Terms: https://www.naturalearthdata.com/about/terms-of-use/

`north_america.geojson` is retained as a legacy asset but is no longer used by
the map. The global dataset is also used by location selection and Demo Mode.

Alert geometry is supplied separately by the National Weather Service at runtime.


## Offline city/ZIP catalog

`us_places.tsv.gz` is a derived subset of the **GeoNames US postal-code dataset**,
provided by [GeoNames](https://www.geonames.org/) under the
[Creative Commons Attribution 4.0 license](https://creativecommons.org/licenses/by/4.0/).

Source mirror: https://github.com/symerio/postal-codes-data/blob/master/data/geonames/US.txt
Original distribution: https://download.geonames.org/export/zip/
Source SHA-256: `36bfc8c52c9acbc2dfd5e3d7f954389640b42b6434ae08e7f6bf95d6b24f5161`

Changes: retained postal code, place name, state code, latitude, and longitude;
omitted records without usable US state/territory codes or coordinates; stored
as compressed UTF-8 TSV. There are 40,970 entries. This is a bundled snapshot,
not a live postal registry, and does not cover every place or territory. Pin
coordinates are approximate postal-area centers, not street addresses. ZIP+4
search uses its five-digit base ZIP.

City names and nearby-place labels support offline location setup. Official NWS
zone resolution still occurs over HTTPS when a user saves a location.

## State, county, and city context

`us_states.geojson` is the US subset (51 features) of Natural Earth's public-domain
1:50m admin-1 state/province boundaries. Source:
https://github.com/nvkelso/natural-earth-vector/blob/master/geojson/ne_50m_admin_1_states_provinces.geojson

`us_counties.geojson` contains 3,221 county features from the US Census-derived
Plotly dataset: https://github.com/plotly/datasets/blob/master/geojson-counties-fips.json
Only the display name and original geometry are retained. Boundaries are snapshots
for geographic context, not current jurisdictional, surveying, or navigation data.
County context is optional and appears only after zooming in. Major-city labels
use a small bundled list of approximate city-center coordinates in `map_context.py`.

Bundled geometry SHA-256 values:

- `us_states.geojson`: `b1121a045f58f9fd026b7fa60b9bf9688fd734fe92087ce0e48490f8ec92298e`
- `us_counties.geojson`: `0968b870b6288e4772afe6819ae7b76b2ba7241aa727a522288c290fa8f05f03`
