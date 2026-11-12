import assert from "node:assert/strict";
import test from "node:test";
import { add } from "../src/calculator.js";

test("add simple", () => {
  assert.equal(add(2, 2), 4);
});

test("add zeros", () => {
  assert.equal(add(0, 5), 5);
});
