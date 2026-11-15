import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";

const root = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../..",
);
const workspace = await mkdtemp(path.join(tmpdir(), "leanguard-approval-"));
const child = spawn(
  process.env.LEANGUARD_TEST_PYTHON ?? path.join(root, ".venv/bin/python"),
  ["tests/workbench/approval_fixture.py", workspace],
  { cwd: root, stdio: ["ignore", "pipe", "inherit"] },
);
const url = await new Promise((resolve, reject) => {
  const timeout = setTimeout(
    () => reject(new Error("Approval UI did not start")),
    30000,
  );
  child.once("error", reject);
  child.once("exit", (code) => reject(new Error(`Fixture exited: ${code}`)));
  child.stdout.once("data", (data) => {
    clearTimeout(timeout);
    resolve(data.toString().trim());
  });
});
const browser = await chromium.launch({ headless: true });
try {
  const context = await browser.newContext();
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(url);
  await page.getByRole("button", { name: "Approve this exact call" }).waitFor();
  assert.equal(new URL(page.url()).hash, "");
  assert.match(
    await page.locator("#proposals").innerText(),
    /9007199254740993/,
  );
  assert.equal(await page.locator("img").count(), 0);
  await page.getByRole("button", { name: "Approve this exact call" }).click();
  await page.getByRole("button", { name: "Revoke approval" }).waitFor();
  assert.match(
    await page.locator("#notice").innerText(),
    /No tool was executed/,
  );
  await page.getByRole("button", { name: "Revoke approval" }).click();
  await page.waitForFunction(() =>
    document
      .getElementById("proposals")
      .textContent.includes("Status: rejected"),
  );
  assert.equal(await page.locator("#proposals button").count(), 0);
  const result = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  assert.deepEqual(
    result.violations.map((v) => v.id),
    [],
  );
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
    true,
  );
  assert.deepEqual(errors, []);
  console.log(
    "Browser exact-proposal approval, revocation, escaping, integer fidelity and accessibility passed.",
  );
} finally {
  await browser.close();
  child.kill("SIGTERM");
  await rm(workspace, { recursive: true, force: true });
}
