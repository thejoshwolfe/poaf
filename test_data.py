
data = [
    {
        "description": "flags parity failure",
        "contents": { "hex": "bef6fc" "00" },
        "result": "error",
    },
    {
        "description": "empty archive 0",
        "contents": { "hex": "bef6fc" "f0" },
        "result": [],
    },
    {
        "description": "impossible flags 1",
        "contents": { "hex": "bef6fc" "e1" },
        "result": "error",
    },
    {
        "description": "impossible flags 2",
        "contents": { "hex": "bef6fc" "d2" },
        "result": "error",
    },
    {
        "description": "impossible flags 3",
        "contents": { "hex": "bef6fc" "c3" },
        "result": "error",
    },
    {
        "description": "empty archive 4",
        "contents": { "hex": "bef6fc" "b4" },
        "result": [],
    },
    {
        "description": "empty archive 5",
        "contents": { "hex": "bef6fc" "a5" "0300" },
        "result": [],
    },
    {
        "description": "empty archive 6",
        "contents": { "hex": "bef6fc" "96" },
        "result": [],
    },
    {
        "description": "empty archive 7",
        "contents": { "hex": "bef6fc" "87" "0300" },
        "result": [],
    },
    {
        "description": "empty archive 8",
        "contents": { "hex": "bef6fc" "78" "0400000000000000" "04" "eee9cf" },
        "result": [],
    },
    {
        "description": "empty archive 9",
        "contents": { "hex": "bef6fc" "69" "0300" "0400000000000000" "04" "eee9cf" },
        "result": [],
    },
    {
        "description": "empty archive 10",
        "contents": { "hex": "bef6fc" "5a" "00000000" "0400000000000000" "04" "eee9cf" },
        "result": [],
    },
    {
        "description": "empty archive 11",
        "contents": { "hex": "bef6fc" "4b" "0300" "00000000" "0400000000000000" "04" "eee9cf" },
        "result": [],
    },
    {
        "description": "empty archive 12",
        "contents": { "hex": "bef6fc" "3c" "dcac0000" "0800000000000000" "08" "eee9cf" },
        "result": [],
    },
    {
        "description": "empty archive 13",
        "contents": { "hex": "bef6fc" "2d" "0300" "0300" "0600000000000000" "06" "eee9cf" },
        "result": [],
    },
    {
        "description": "empty archive 14",
        "contents": { "hex": "bef6fc" "1e" "dcac0000" "00000000" "0800000000000000" "08" "eee9cf" },
        "result": [],
    },
    {
        "description": "empty archive 15",
        "contents": { "hex": "bef6fc" "0f" "0300" "0300" "00000000" "0600000000000000" "06" "eee9cf" },
        "result": [],
    },
]
