#!/bin/sh
set -eu

mihomo_repo=MetaCubeX/mihomo
zashboard_repo=Zephyruso/zashboard

fetch() {
    curl --disable --fail --silent --show-error --location \
        --proto '=https' --proto-redir '=https' --retry 3 --retry-max-time 120 \
        --max-time 120 --output "$2" "$1"
}

release_tag() {
    jq -er '
        select(.draft == false and .prerelease == false)
        | .tag_name
        | strings
        | select(test("^[A-Za-z0-9][A-Za-z0-9._-]*$"))
    ' "$1"
}

fetch_license() {
    license_json="$3.json"
    fetch "https://api.github.com/repos/$1/contents/LICENSE?ref=$2" "$license_json"
    expected=$(jq -er '
        select(.type == "file" and .encoding == "base64")
        | .sha
        | strings
        | select(test("^[0-9a-f]{40}$"))
    ' "$license_json")
    encoded=$(jq -er '.content | strings' "$license_json")
    printf '%s' "$encoded" | base64 -d > "$3"
    test -s "$3"
    length=$(wc -c < "$3" | tr -d '[:space:]')
    actual=$( { printf 'blob %s\0' "$length"; cat "$3"; } | sha1sum)
    if [ "${actual%% *}" != "$expected" ]; then
        printf 'License Git blob checksum mismatch for %s %s\n' "$1" "$2" >&2
        return 1
    fi
}

fetch_asset() {
    if ! digest=$(jq -er --arg asset "$4" '
        .assets[]
        | select(.name == $asset and .state == "uploaded")
        | .digest
        | strings
        | select(test("^sha256:[0-9a-f]{64}$"))
    ' "$3"); then
        printf 'Missing asset or SHA-256 for %s %s (%s)\n' "$1" "$2" "$4" >&2
        return 1
    fi
    fetch "https://github.com/$1/releases/download/$2/$4" "$5"
    printf '%s  %s\n' "${digest#sha256:}" "$5" | sha256sum -c -
}

if [ "$1" = resolve ]; then
    fetch "https://api.github.com/repos/$mihomo_repo/releases/latest" mihomo-release.json
    fetch "https://api.github.com/repos/$zashboard_repo/releases/latest" zashboard-release.json
    mihomo_tag=$(release_tag mihomo-release.json)
    zashboard_tag=$(release_tag zashboard-release.json)
    printf 'Mihomo %s\nZashboard %s\n' "$mihomo_tag" "$zashboard_tag" > versions
    cat versions
    fetch_license "$mihomo_repo" "$mihomo_tag" mihomo.LICENSE
    fetch_license "$zashboard_repo" "$zashboard_tag" zashboard.LICENSE
    exit 0
fi

case "$2" in
    amd64) mihomo_platform=linux-amd64-v1 ;;
    arm64) mihomo_platform=linux-arm64 ;;
    *) printf 'Unsupported architecture: %s\n' "$2" >&2; exit 1 ;;
esac

mihomo_tag=$(release_tag mihomo-release.json)
zashboard_tag=$(release_tag zashboard-release.json)
fetch_asset "$mihomo_repo" "$mihomo_tag" mihomo-release.json "mihomo-$mihomo_platform-$mihomo_tag.gz" mihomo.gz
fetch_asset "$zashboard_repo" "$zashboard_tag" zashboard-release.json dist-no-fonts.zip zashboard.zip

gzip -dc mihomo.gz > mihomo
chmod 0755 mihomo
upx --best --lzma mihomo
upx --test mihomo
chmod 0555 mihomo
unzip -q zashboard.zip
test -s dist/index.html
test -s dist/THIRD_PARTY_NOTICES.md
