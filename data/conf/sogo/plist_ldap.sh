#!/bin/bash
set -eu

# Keep the existing, operator-customizable legacy template as the source.
export line="${1:?domain required}"
export gal="${2:?GAL setting required}"
exec envsubst < /etc/sogo/plist_ldap
