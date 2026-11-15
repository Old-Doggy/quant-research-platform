async (page) => {
  await page.getByRole('heading', {name:'行情与研究',exact:true}).waitFor();
  await page.locator('[data-testid="stStatusWidget"]').waitFor({state:'hidden'});
  const navigation = await page.locator('[data-testid="stRadioOption"]').evaluateAll(els => els.map(el=>({
    text:el.innerText, color:getComputedStyle(el.querySelector('p')).color,
    background:getComputedStyle(el).backgroundColor, width:el.getBoundingClientRect().width,
    height:el.getBoundingClientRect().height, selected:!!el.querySelector('input:checked')
  })));
  const frames = page.frames().map(f=>({url:f.url(),name:f.name()}));
  return {navigation,frames,context:await page.locator('.quant-context-status').innerText()};
}
