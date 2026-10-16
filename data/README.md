# Offline map outlines

`north_america.geojson` contains the United States, Canada, Mexico, Cuba, and
Bahamas geometries from Natural Earth's public-domain 1:110m country dataset.
Used for geographic context only, not precise boundaries or navigation.

Source: https://github.com/nvkelso/natural-earth-vector/blob/master/geojson/ne_110m_admin_0_countries.geojson
Terms: https://www.naturalearthdata.com/about/terms-of-use/

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
