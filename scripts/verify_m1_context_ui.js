async (page) => {
  await page.getByText('策略', { exact: true }).first().click();
  await page.getByRole('heading', { name: '策略研究', exact: true }).waitFor();
  const select = page.locator('.st-key-explicit_strategy_strategy [role="combobox"]');
  await select.click();
  await page.getByRole('option', { name: '质量动量', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('.st-key-run_explicit_strategy button')?.disabled);
  const blocked = await page.getByRole('button', { name: '运行研究', exact: true }).isDisabled();
  const explanation = await page.getByText(/财务与股东特征缺少可用时点/).innerText();
  await page.screenshot({ path: 'output/playwright/m1-financial-gate.png', scale: 'css' });
  await select.click();
  await page.getByRole('option', { name: '趋势跟踪', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('.st-key-run_explicit_strategy button')?.disabled === false);
  await page.getByRole('button', { name: '运行研究', exact: true }).click();
  await page.getByText('策略净值', { exact: true }).first().waitFor({ timeout: 60000 });
  const strategyUrl = page.url();
  await page.getByText('作品', { exact: true }).first().click();
  await page.getByRole('heading', { name: '研究作品与工程实践', exact: true }).waitFor();
  await page.goBack();
  await page.getByRole('heading', { name: '策略研究', exact: true }).waitFor();
  const restoredUrl = page.url();
  await page.reload();
  await page.getByRole('heading', { name: '策略研究', exact: true }).waitFor();
  return { blocked, explanation, strategyUrl, restoredUrl,
    exceptions: await page.locator('[data-testid="stException"]').allTextContents() };
}
