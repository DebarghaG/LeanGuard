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
const workspace = await mkdtemp(path.join(tmpdir(), "leanguard-browser-"));
const child = spawn(
  process.env.LEANGUARD_TEST_PYTHON ?? path.join(root, ".venv/bin/python"),
  ["-m", "leanguard.workbench", "--project", root, "--workspace", workspace],
  { cwd: root, stdio: ["ignore", "pipe", "inherit"] },
);
const url = await new Promise((resolve, reject) => {
  const timeout = setTimeout(
    () => reject(new Error("Workbench did not start")),
    30000,
  );
  child.once("error", reject);
  child.once("exit", (code) => reject(new Error(`Workbench exited: ${code}`)));
  child.stdout.once("data", (data) => {
    clearTimeout(timeout);
    resolve(data.toString().trim());
  });
});
const browser = await chromium.launch({ headless: true });
try {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
  });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(url);
  await page.locator("#pack-name").waitFor();
  await page.waitForFunction(
    () => document.getElementById("pack-name").value === "documents",
  );
  assert.equal(new URL(page.url()).hash, "");
  await page
    .getByLabel("Maximum approval age, in seconds (blank = unbounded)")
    .fill("30");
  await page
    .getByLabel("What one amount unit means")
    .fill("<img src=x onerror=alert(1)>");
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await page.waitForFunction(() =>
    document.getElementById("save-state").textContent.includes("Saved"),
  );
  await page
    .getByRole("button", { name: "Compile and audit this draft" })
    .click();
  await page.waitForFunction(
    () => document.getElementById("stage").textContent === "Compiled",
    null,
    { timeout: 180000 },
  );
  await page.locator('[data-view="inspect"]').click();
  assert.match(
    await page.locator("#inspection-rules").innerText(),
    /30 seconds/,
  );
  const checkA11y = async () => {
    const result = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    assert.deepEqual(
      result.violations.map((v) => ({
        id: v.id,
        nodes: v.nodes.map((n) => n.target),
      })),
      [],
    );
  };
  await checkA11y();
  await page.locator('[data-view="scenarios"]').click();
  await page.locator("#run-scenarios").click();
  await page.waitForFunction(
    () => document.querySelectorAll("#scenario-results article").length === 3,
  );
  assert.match(
    await page.locator("#scenario-results").innerText(),
    /approved-write/,
  );
  await checkA11y();
  await page.locator('[data-view="review"]').click();
  await page.locator("#create-bundle").click();
  await page
    .getByRole("button", { name: "Accept this exact bundle" })
    .waitFor();
  await page.getByRole("button", { name: "Accept this exact bundle" }).click();
  await page.waitForFunction(() =>
    document
      .getElementById("bundle-details")
      .textContent.includes("Review accepted"),
  );
  await checkA11y();
  await page.locator('[data-view="author"]').click();
  await checkA11y();
  assert.equal(await page.locator("img").count(), 0);
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
    true,
  );
  await checkA11y();
  if (process.env.LEANGUARD_SCREENSHOT)
    await page.screenshot({
      path: process.env.LEANGUARD_SCREENSHOT,
      fullPage: true,
    });
  assert.deepEqual(errors, []);
  console.log(
    "Browser policy authoring, native scenarios, artifact review, mobile layout and accessibility passed.",
  );
} finally {
  await browser.close();
  child.kill("SIGTERM");
  await rm(workspace, { recursive: true, force: true });
}
