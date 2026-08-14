// One-off Playwright driver for manually verifying the app in a real
// browser (no chromium-cli available in this environment). Not part of the
// test suite -- run with `node scripts/browser_check.mjs`.
import { chromium } from "playwright";

const BASE_URL = process.argv[2] || "http://localhost:5173";
const SHOT_DIR = "/tmp/rbt_screenshots";
await import("node:fs/promises").then((fs) => fs.mkdir(SHOT_DIR, { recursive: true }));

const browser = await chromium.launch({ args: ["--no-sandbox"] });
const page = await (await browser.newContext()).newPage();

const consoleErrors = [];
page.on("console", (msg) => {
  if (msg.type() === "error") {
    consoleErrors.push(msg.text());
    console.log("  [console error]", msg.text());
  }
});
page.on("pageerror", (err) => {
  consoleErrors.push(`pageerror: ${err.message}`);
  console.log("  [pageerror]", err.message);
});

async function shot(name) {
  await page.screenshot({ path: `${SHOT_DIR}/${name}.png`, fullPage: true });
  console.log(`  screenshot: ${SHOT_DIR}/${name}.png`);
}

try {
  console.log("1. nav to app (should show sign-in, RLS blocks everything unauthenticated)");
  await page.goto(BASE_URL, { waitUntil: "networkidle" });
  await page.waitForSelector("text=Sign in", { timeout: 15000 });
  await shot("01_signin");

  console.log("2. sign in");
  await page.fill('input[type="email"]', "driver@redbull-telemetry.local");
  await page.fill('input[type="password"]', "test-password-123");
  await page.click('button:has-text("Sign in")');
  await page.waitForSelector("text=Overview", { timeout: 15000 });
  await shot("02_overview");

  console.log("3. Sessions -> explorer");
  await page.click('button:has-text("Sessions")');
  await page.waitForSelector("text=Hungarian Grand Prix", { timeout: 15000 });
  await shot("03_sessions");

  console.log("4. open a session (Race)");
  await page.click('button:has-text("Race")');
  await page.waitForSelector("table", { timeout: 15000 });
  await shot("04_session_results");

  console.log("5. Laps tab");
  await page.click('.tabs >> text=Laps');
  await page.waitForSelector("text=Lap time evolution", { timeout: 20000 });
  // Only 2 drivers have telemetry in this scoped test ingestion -- pick one
  // that actually does, so the telemetry screenshot shows real chart data.
  await page.selectOption("select", { label: "Lando Norris" });
  await page.waitForTimeout(1000);
  await shot("05_laps");

  console.log("6. open telemetry for a lap");
  const telemetryButtons = await page.$$('tbody button:has-text("Telemetry")');
  if (telemetryButtons.length > 0) {
    await telemetryButtons[0].click();
    await page.waitForSelector(".chart-shell", { timeout: 15000 });
    await shot("06_telemetry");
  } else {
    console.log("  (no Telemetry buttons found on Laps tab)");
  }

  console.log("7. Compare tab");
  await page.click('.tabs >> text=Compare');
  await page.waitForTimeout(2000);
  await shot("07_compare");

  console.log("8. Setup tab");
  await page.click('.tabs >> text=Setup');
  await page.waitForSelector("text=Stints", { timeout: 15000 });
  await shot("08_setup");

  console.log("\nconsole errors captured:", consoleErrors.length);
  consoleErrors.forEach((e) => console.log("  -", e));
} catch (err) {
  console.error("DRIVER FAILED:", err.message);
  await shot("failure");
  process.exitCode = 1;
} finally {
  await browser.close();
}
