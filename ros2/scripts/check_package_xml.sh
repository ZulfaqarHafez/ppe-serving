#!/usr/bin/env bash
# Validate every package.xml against the ROS package format 3 schema.
# ament_xmllint is switched off in the packages because libxml2 on Ubuntu 24.04
# will not fetch the schema over http; this fetches it with curl and points
# xmllint at the local copy through an XML catalog.
set -euo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
curl -fsSL http://download.ros.org/schema/package_format3.xsd -o "$tmp/package_format3.xsd"
cat > "$tmp/catalog.xml" <<CAT
<?xml version="1.0"?>
<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">
  <uri name="http://download.ros.org/schema/package_format3.xsd" uri="file://$tmp/package_format3.xsd"/>
</catalog>
CAT
XML_CATALOG_FILES="$tmp/catalog.xml" xmllint --noout \
  --schema http://download.ros.org/schema/package_format3.xsd src/*/package.xml
