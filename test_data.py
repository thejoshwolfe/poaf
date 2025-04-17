
data = [
    {
        "description": "invalid ArchiveHeader",
        "contents": { "hex": "BEF6F29E" "0300" },
        "result": "error",
    },
    {
        "description": "empty archive both",
        "contents": { "hex": "BEF6F09F" "0300" "0300" "00000000" "0600000000000000" "06" "eee9cf" },
        "result": [],
    },
    {
        "description": "unexpected EOF after ArchiveHeader",
        "contents": { "hex": "BEF6F09F" },
        "result": "error",
    },
    {
        "description": "unexpected EOF in Data Region",
        "contents": { "hex": "BEF6F09F" "03" },
        "result": "error",
    },
]
