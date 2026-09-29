// Capture the live public workspace. Only illustrative inputs are typed.
import { chromium } from "playwright-core";
import { execFileSync } from "node:child_process";
import { mkdir, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const clips = resolve("public/clips");
const mode = process.argv[2];
if (!["food", "fresh", "fresh-evidence"].includes(mode))
  throw new Error(
    "Usage: node scripts/record-live.mjs food|fresh|fresh-evidence",
  );
await mkdir(clips, { recursive: true });
const browser = await chromium.launch({
  headless: true,
  executablePath: "/usr/bin/google-chrome-stable",
  args: ["--no-sandbox"],
});

async function record(name, action) {
  const temp = await mkdtemp(join(tmpdir(), "packsense-capture-"));
  const context = await browser.newContext({
    viewport: { width: 1600, height: 900 },
    deviceScaleFactor: 1,
    recordVideo: { dir: temp, size: { width: 1600, height: 900 } },
  });
  const page = await context.newPage();
  await page.goto("https://packsense-web.vercel.app", {
    waitUntil: "domcontentloaded",
  });
  await action(page);
  await page.waitForTimeout(500);
  const video = page.video();
  await context.close();
  const raw = await video.path();
  const output = join(clips, `${name}.mp4`);
  execFileSync("ffmpeg", [
    "-y",
    "-loglevel",
    "error",
    "-i",
    raw,
    "-an",
    "-r",
    "30",
    "-c:v",
    "libx264",
    "-preset",
    "medium",
    "-crf",
    "24",
    "-pix_fmt",
    "yuv420p",
    "-movflags",
    "+faststart",
    output,
  ]);
  await rm(temp, { recursive: true, force: true });
  console.log(name, output);
}

try {
  if (mode === "food")
    await record("food-and-journey", async (page) => {
      await page.locator("[data-enter-app]").click();
      await page
        .locator('[data-nav="evaluate"]')
        .waitFor({ state: "visible", timeout: 90000 });
      await page.locator('[data-nav="evaluate"]').click();
      await page.waitForTimeout(650);
      await page
        .locator("#food-search")
        .pressSequentially("asparagus", { delay: 100 });
      await page
        .locator("#food-search-results [data-food-id]")
        .first()
        .waitFor({ timeout: 20000 });
      await page.waitForTimeout(800);
      await page.locator("#food-search-results [data-food-id]").first().click();
      await page.waitForTimeout(1100);
      await page.locator('[name="desired_shelf_life_days"]').fill("5");
      await page.locator('[name="storage_type"]').selectOption("chilled");
      await page.locator('[name="storage_temperature_c"]').fill("4");
      await page.locator('[name="storage_relative_humidity_pct"]').fill("90");
      await page.waitForTimeout(700);
      await page.evaluate(() =>
        window.scrollTo({ top: 540, behavior: "smooth" }),
      );
      await page.waitForTimeout(850);
      await page.locator('[name="transport_mode"]').selectOption("road");
      await page.locator('[name="transport_duration_hours"]').fill("6");
      await page.locator('[name="transport_temperature_c"]').fill("4");
      await page.locator('[name="transport_max_temperature_c"]').fill("8");
      await page
        .locator('[name="transport_handling_severity"]')
        .selectOption("low");
      await page.locator('[name="net_pack_quantity"]').fill("150");
      await page.locator('[name="net_pack_quantity_unit"]').selectOption("g");
      await page.waitForTimeout(1400);
    });
  if (mode === "fresh" || mode === "fresh-evidence")
    await record(
      mode === "fresh" ? "fresh-evaluation" : "fresh-evidence-full",
      async (page) => {
        await page.locator("[data-enter-app]").click();
        await page
          .locator('[data-nav="evaluate"]')
          .waitFor({ state: "visible", timeout: 90000 });
        await page.locator('[data-nav="evaluate"]').click();
        await page.locator("#food-search").fill("asparagus");
        await page
          .locator("#food-search-results [data-food-id]")
          .first()
          .waitFor({ timeout: 20000 });
        await page
          .locator("#food-search-results [data-food-id]")
          .first()
          .click();
        await page.locator('[name="desired_shelf_life_days"]').fill("5");
        await page.locator('[name="storage_type"]').selectOption("chilled");
        await page.locator('[name="storage_temperature_c"]').fill("4");
        await page.locator('[name="storage_relative_humidity_pct"]').fill("90");
        await page.locator('[name="transport_mode"]').selectOption("road");
        await page.locator('[name="transport_duration_hours"]').fill("6");
        await page.locator('[name="transport_temperature_c"]').fill("4");
        await page.locator('[name="transport_max_temperature_c"]').fill("8");
        await page
          .locator('[name="transport_handling_severity"]')
          .selectOption("low");
        await page.locator('[name="net_pack_quantity"]').fill("150");
        await page.locator('[name="net_pack_quantity_unit"]').selectOption("g");
        await page.evaluate(() =>
          window.scrollTo({
            top: document.body.scrollHeight,
            behavior: "instant",
          }),
        );
        await page.waitForTimeout(900);
        await page.locator("#evaluate-submit").click();
        await page
          .locator("#decisions-loaded:not([hidden])")
          .waitFor({ timeout: 90000 });
        await page.waitForTimeout(2100);
        await page.evaluate(() =>
          window.scrollTo({ top: 630, behavior: "smooth" }),
        );
        await page.waitForTimeout(1600);
        if (mode === "fresh-evidence") {
          await page.evaluate(() =>
            window.scrollTo({ top: 0, behavior: "instant" }),
          );
          await page.locator('[data-nav="evidence"]').click();
          await page.waitForTimeout(1100);
          await page.evaluate(() =>
            window.scrollTo({ top: 450, behavior: "smooth" }),
          );
          await page.waitForTimeout(1700);
          await page.evaluate(() =>
            window.scrollTo({ top: 0, behavior: "smooth" }),
          );
          await page.waitForTimeout(1000);
        }
      },
    );
  if (mode === "fresh") {
    execFileSync("ffmpeg", [
      "-y",
      "-loglevel",
      "error",
      "-ss",
      "8",
      "-i",
      join(clips, "fresh-evaluation.mp4"),
      "-vf",
      "tpad=stop_mode=clone:stop_duration=3",
      "-t",
      "9",
      "-an",
      "-c:v",
      "libx264",
      "-crf",
      "23",
      "-pix_fmt",
      "yuv420p",
      "-movflags",
      "+faststart",
      join(clips, "fresh-result.mp4"),
    ]);
  }
  if (mode === "fresh-evidence") {
    execFileSync("ffmpeg", [
      "-y",
      "-loglevel",
      "error",
      "-ss",
      "12",
      "-i",
      join(clips, "fresh-evidence-full.mp4"),
      "-vf",
      "tpad=stop_mode=clone:stop_duration=3",
      "-t",
      "9",
      "-an",
      "-c:v",
      "libx264",
      "-crf",
      "23",
      "-pix_fmt",
      "yuv420p",
      "-movflags",
      "+faststart",
      join(clips, "fresh-evidence.mp4"),
    ]);
  }
} finally {
  await browser.close();
}
