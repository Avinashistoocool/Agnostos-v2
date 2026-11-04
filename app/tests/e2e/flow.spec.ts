import { expect, test, type Page } from "@playwright/test";

const shot = (page: Page, name: string) => page.screenshot({ path: `screenshots/${name}.png` });

test("full flow against the mock engine", async ({ page }) => {
  await page.goto("/?fast");

  // Sign-in
  await expect(page.getByText("research outreach, done honestly")).toBeVisible();
  await shot(page, "01-sign-in");
  await page.getByRole("button", { name: "Continue as guest" }).click();

  // Onboarding: resume
  await expect(page.getByRole("heading", { name: "Start with your resume" })).toBeVisible();
  await page.getByTestId("resume-input").setInputFiles({ name: "resume.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4") });
  await expect(page.getByText("Imported", { exact: true })).toBeVisible();
  await shot(page, "02-onboarding-resume");
  await page.getByTestId("next").click();

  // profile
  await expect(page.getByRole("heading", { name: "Does this look right?" })).toBeVisible();
  await expect(page.getByLabel("Full name")).toHaveValue("Aarav Sharma");
  await shot(page, "03-onboarding-profile");
  await page.getByTestId("next").click();

  // interests
  await expect(page.getByRole("heading", { name: "What do you want to work on?" })).toBeVisible();
  await page.getByRole("button", { name: "+ HEP / CERN" }).click();
  await page.getByTestId("next").click();

  // targets
  await expect(page.getByRole("heading", { name: "Where would you like to go?" })).toBeVisible();
  await page.getByRole("button", { name: "USA", exact: true }).click();
  await shot(page, "04-onboarding-targets");
  await page.getByTestId("next").click();

  // email: SMTP preset + test
  await expect(page.getByRole("heading", { name: "Connect your email" })).toBeVisible();
  await page.getByRole("radio", { name: /SMTP \/ IMAP/ }).click();
  await page.getByRole("button", { name: "Outlook" }).click();
  await page.getByLabel("Username").fill("aarav@outlook.com");
  await page.getByRole("button", { name: "Test sending" }).click();
  await expect(page.getByText(/SMTP login OK/)).toBeVisible();
  await shot(page, "05-onboarding-email");
  await page.getByTestId("next").click();

  // llm
  await expect(page.getByRole("heading", { name: "Choose a writing model" })).toBeVisible();
  await page.getByLabel("API key").fill("gsk_test_abcd");
  await page.getByRole("button", { name: "Test", exact: true }).click();
  await expect(page.getByText("Connected to groq")).toBeVisible();
  await page.getByTestId("next").click();

  // funding
  await expect(page.getByRole("heading", { name: "Can you fund yourself?" })).toBeVisible();
  await page.getByRole("radio", { name: /Yes, I can self-fund/ }).click();
  await page.getByTestId("next").click();

  // limits
  await expect(page.getByRole("heading", { name: "How fast should we send?" })).toBeVisible();
  await shot(page, "06-onboarding-limits");
  await page.getByTestId("next").click();
  await expect(page.getByText("You're all set")).toBeVisible();
  await page.getByRole("button", { name: "Go to dashboard" }).click();

  // Dashboard
  await expect(page.getByTestId("kpis").getByText("Professors")).toBeVisible();
  await expect(page.getByRole("img", { name: /Emails sent per day/ })).toBeVisible();
  await shot(page, "07-dashboard");

  // Professors: edit a draft
  await page.getByRole("link", { name: "Professors" }).click();
  await page.getByText("Prof. Dr. Lena Hartmann").click();
  const body = page.getByLabel("Email", { exact: true });
  await expect(body).toBeVisible();
  await body.fill("Dear Professor Hartmann,\n\nEdited by the e2e test.\n\nBest,\nAarav");
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByText("Draft saved")).toBeVisible();
  await shot(page, "08-professors-draft");
  // sent rows are read-only
  await page.getByText("Dr. Matteo Rossi").click();
  await expect(page.getByText("Already sent, so this is read-only.")).toBeVisible();

  // Replies: approve with confirmation
  await page.getByRole("link", { name: "Replies" }).click();
  const card = page.getByTestId("reply-0");
  await expect(card.getByText("Needs review")).toBeVisible();
  await card.getByRole("switch", { name: "Approved to send" }).click();
  const dlg = page.getByRole("dialog", { name: "Approve this reply?" });
  await expect(dlg).toContainText("Approved replies may be sent");
  await shot(page, "09-replies-confirm");
  await dlg.getByRole("button", { name: "Approve" }).click();
  await expect(card.getByText("Approved", { exact: true })).toBeVisible();
  await expect(card.getByRole("switch", { name: "Approved to send" })).toHaveAttribute("aria-checked", "true");

  // Conversations
  await page.getByRole("link", { name: "Conversations" }).click();
  await expect(page.frameLocator("iframe[title=Conversations]").getByText("Dr. Matteo Rossi · CERN")).toBeVisible();
  await shot(page, "10-conversations");

  // Pipeline: dry-run send, answer the [Y/N] prompt, watch logs
  await page.getByRole("link", { name: "Pipeline" }).click();
  await shot(page, "11-pipeline");
  await page.getByTestId("cmd-send").click();
  await expect(page.getByTestId("start-job")).toHaveText(/Start dry run/);
  await page.getByTestId("start-job").click();
  await expect(page.getByTestId("job-log")).toContainText("DRY RUN");
  await expect(page.getByTestId("prompt-banner")).toBeVisible();
  await shot(page, "12-jobs-prompt");
  await page.getByRole("button", { name: "Yes, continue" }).click();
  await expect(page.getByTestId("job-log")).toContainText("Finished:");
  await expect(page.getByTestId("prompt-banner")).toHaveCount(0);
  await shot(page, "13-jobs-done");

  // Live run requires typed confirmation
  await page.getByRole("link", { name: "Pipeline" }).click();
  await page.getByTestId("cmd-send").click();
  await page.getByRole("switch", { name: "Send for real" }).click();
  const start = page.getByTestId("start-job");
  await expect(start).toHaveText(/Start live run/);
  await expect(start).toBeDisabled();
  await page.getByLabel(/to confirm/).fill("send live");
  await expect(start).toBeDisabled();
  await page.getByLabel(/to confirm/).fill("SEND LIVE");
  await expect(start).toBeEnabled();
  await shot(page, "14-pipeline-live-confirm");
  await start.click();
  await expect(page.getByTestId("job-log")).toContainText("LIVE MODE");
  await expect(page.getByRole("heading", { name: "send" })).toBeVisible();

  // Settings
  await page.getByRole("link", { name: "Settings" }).click();
  await page.getByRole("button", { name: "About" }).click();
  await expect(page.getByTestId("app-version")).toHaveText("0.1.0");
  await page.getByRole("button", { name: "Sending limits" }).click();
  await shot(page, "15-settings");
});

test("GitHub device flow shows the code and signs in", async ({ page }) => {
  await page.goto("/?fast");
  await page.getByTestId("github").click();
  await expect(page.getByTestId("gh-code")).toHaveText("WDJB-MJHT");
  await shot(page, "16-github-device");
  await expect(page.getByRole("heading", { name: "Start with your resume" })).toBeVisible({ timeout: 15_000 });
});
