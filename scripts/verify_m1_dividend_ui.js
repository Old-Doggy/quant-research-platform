async (page) => {
  await page.getByText('组合', { exact: true }).first().click();
  await page.getByRole('heading', { name: '组合研究', exact: true }).waitFor();
  await page.getByRole('button', { name: '运行组合研究', exact: true }).click();
  await page.getByText('期末现金权重', { exact: true }).waitFor({ timeout: 60000 });
  await page.getByText('净值与回撤', { exact: true }).click();
  await page.locator('[data-testid="stPlotlyChart"]').first().waitFor();
  const navCharts = await page.locator('[data-testid="stPlotlyChart"]').count();
  await page.getByText('现金与持仓', { exact: true }).click();
  await page.getByText('当日现金', { exact: true }).waitFor();
  await page.screenshot({ path: 'output/playwright/m1-dividend-portfolio.png', scale: 'css' });
  return { navCharts, exceptions: await page.locator('[data-testid="stException"]').allTextContents(),
    cashVisible: await page.getByText('当日现金', { exact: true }).isVisible() };
}
