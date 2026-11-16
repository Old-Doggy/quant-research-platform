async (page) => {
  await page.getByRole('spinbutton', {name:'成交额至少（亿元）',exact:true}).fill('1');
  await page.getByRole('spinbutton', {name:'成交额至少（亿元）',exact:true}).press('Enter');
  await page.getByText('1 / 2',{exact:true}).waitFor();
  await page.getByTestId('stStatusWidget').waitFor({state:'hidden'});
  const graphs=await page.locator('.js-plotly-plot').evaluateAll(nodes=>nodes.filter(n=>n.data).map(n=>({
    x:n.data[0].x,y:n.data[0].y,ids:n.data[0].customdata,hover:n.data[0].hovertemplate
  })));
  await page.getByRole('textbox',{name:'保存名称',exact:true}).fill('真实行情成交额1亿');
  await page.getByText('保存本次筛选',{exact:true}).click();
  await page.getByText('已保存条件、行情版本和完整证券名单。',{exact:true}).waitFor();
  await page.getByTestId('stStatusWidget').waitFor({state:'hidden'});
  await page.screenshot({path:'output/playwright/m3-screen-saved.png',fullPage:true});
  const exceptions=await page.getByTestId('stException').allTextContents();
  return {graphs,exceptions};
}
