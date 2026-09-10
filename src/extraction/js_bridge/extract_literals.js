#!/usr/bin/env node
/**
 * Parses JS with Acorn and extracts ONLY literal-safe top-level const/let
 * declarations. Never executes anything — no eval, no vm, no Function()
 * constructor (plan §6.2, Appendix G #1: node:vm is not a security
 * boundary; parse, don't execute).
 *
 * Reads JS source on stdin. Writes one JSON object to stdout:
 *   { ok: true, literals: { <name>: <value>, ... }, rejected: [{name, kind, reason}] }
 * or { ok: false, error: "..." } if the source doesn't even parse.
 *
 * "Literal-safe" nodes: ObjectExpression, ArrayExpression, string/number/
 * boolean/null Literal, unary minus on a numeric Literal, and a
 * TemplateLiteral with no interpolated expressions. Anything else inside a
 * declarator's init (a call, `new`, a member access, an identifier
 * reference, a function) makes that whole declarator "rejected" — it is
 * never partially evaluated or guessed at.
 */
const acorn = require("acorn");

function readStdin() {
  return new Promise((resolve, reject) => {
    let data = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => (data += chunk));
    process.stdin.on("end", () => resolve(data));
    process.stdin.on("error", reject);
  });
}

class NotLiteralSafe extends Error {}

function evalLiteralNode(node) {
  switch (node.type) {
    case "Literal":
      return node.value;
    case "ObjectExpression": {
      const obj = {};
      for (const prop of node.properties) {
        if (prop.type !== "Property" || prop.computed) {
          throw new NotLiteralSafe(`unsupported object member: ${prop.type}`);
        }
        const key =
          prop.key.type === "Identifier" ? prop.key.name : evalLiteralNode(prop.key);
        obj[key] = evalLiteralNode(prop.value);
      }
      return obj;
    }
    case "ArrayExpression":
      return node.elements.map((el) => (el === null ? null : evalLiteralNode(el)));
    case "UnaryExpression":
      if (node.operator === "-" && node.argument.type === "Literal" &&
          typeof node.argument.value === "number") {
        return -node.argument.value;
      }
      throw new NotLiteralSafe(`unsupported unary expression: ${node.operator}`);
    case "TemplateLiteral":
      if (node.expressions.length > 0) {
        throw new NotLiteralSafe("template literal with interpolated expressions");
      }
      return node.quasis.map((q) => q.value.cooked).join("");
    default:
      throw new NotLiteralSafe(`unsupported node type: ${node.type}`);
  }
}

function extract(source) {
  let ast;
  try {
    ast = acorn.parse(source, { ecmaVersion: "latest", sourceType: "script" });
  } catch (e) {
    return { ok: false, error: `parse error: ${e.message}` };
  }

  const literals = {};
  const rejected = [];

  for (const stmt of ast.body) {
    if (stmt.type !== "VariableDeclaration") continue;
    for (const decl of stmt.declarations) {
      if (decl.id.type !== "Identifier") continue; // skip destructuring, etc.
      const name = decl.id.name;
      if (decl.init === null) continue; // `let x;` with no initializer
      try {
        literals[name] = evalLiteralNode(decl.init);
      } catch (e) {
        rejected.push({ name, kind: decl.init.type, reason: e.message });
      }
    }
  }

  return { ok: true, literals, rejected };
}

readStdin().then((source) => {
  const result = extract(source);
  process.stdout.write(JSON.stringify(result));
  process.exit(result.ok ? 0 : 1);
}).catch((e) => {
  process.stdout.write(JSON.stringify({ ok: false, error: String(e) }));
  process.exit(1);
});
