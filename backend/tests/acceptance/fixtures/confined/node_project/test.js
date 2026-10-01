// A legitimate Node check: it needs a dependency from node_modules and its own sources.
"use strict";
const assert = require("assert");
const add = require("tiny-add");
const { double } = require("./lib");

assert.strictEqual(add(2, 3), 5);
assert.strictEqual(double(4), 8);
console.log("SENTINEL_NODE_FIXTURE ok " + require.resolve("tiny-add"));
