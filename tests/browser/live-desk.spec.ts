import {test,expect} from '@playwright/test';
import {readFile} from 'node:fs/promises';
import {resolve,sep} from 'node:path';

// Browser UI fixtures reuse an actual model-free engine artifact. These tests
// do not register participants, send Switch messages or impersonate approval.
test('live review shows all content, checks, stale state and evidence without publishing',async({page})=>{
  const root=resolve('web');
  const bundle=JSON.parse(await readFile(resolve(root,'examples/reference-release.json'),'utf8'));
  const recorded=bundle.release;
  let releases=[{...recorded,state:'ready',approval:null,receipt:null}];
  const writes:string[]=[];
  await page.route('https://releaseroom.test/**',async route=>{
    const url=new URL(route.request().url());
    if(route.request().method()!=='GET')writes.push(url.pathname);
    if(url.pathname==='/api/config')return route.fulfill({json:{deployment:'controller',available:true,authenticated:true}});
    if(url.pathname==='/api/releases')return route.fulfill({json:{releases}});
    const file=resolve(root,url.pathname==='/'?'index.html':url.pathname.slice(1));
    if(!file.startsWith(root+sep))return route.fulfill({status:404});
    const types:Record<string,string>={'.js':'text/javascript','.css':'text/css','.html':'text/html','.json':'application/json','.svg':'image/svg+xml'};
    const extension=file.slice(file.lastIndexOf('.'));
    try{return await route.fulfill({body:await readFile(file),contentType:types[extension]||'application/octet-stream'});}
    catch{return route.fulfill({status:404});}
  });
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('https://releaseroom.test/');
  await expect(page.getByText('Ready for your decision in Switch.',{exact:true})).toBeVisible();
  await expect(page.locator('.live-diff-row')).toHaveCount(6);
  await expect(page.locator('.approval-command')).toHaveText(`[releaseroom] approve ${recorded.id} ${recorded.digest}`);
  await expect(page.locator('.check-row')).toHaveCount(recorded.report.tests.length);
  await page.getByRole('button',{name:'Check evidence bindings'}).click();
  await expect(page.getByText('✓ Request, content, checks and fingerprint agree.',{exact:true})).toBeVisible();
  const downloading=page.waitForEvent('download');
  await page.getByRole('button',{name:'Download release evidence'}).click();
  expect((await downloading).suggestedFilename()).toBe(`releaseroom-revision-${recorded.revision}-evidence.json`);
  releases=[{...recorded,state:'superseded',approval:null,receipt:null,current_revision:recorded.revision+1}];
  await page.getByRole('button',{name:'Refresh ↻',exact:true}).click();
  await expect(page.getByText('This revision cannot be approved or published.',{exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'Copy approval command'})).toHaveCount(0);
  releases=[{...recorded,state:'published'}];
  await page.getByRole('button',{name:'Refresh ↻',exact:true}).click();
  await expect(page.getByRole('link',{name:'View current verified staging'})).toBeVisible();
  releases=[{...recorded,state:'ready',approval:null,receipt:null,content:{...recorded.content,cta:'Tampered content'}}];
  await page.getByRole('button',{name:'Refresh ↻',exact:true}).click();
  await page.getByRole('button',{name:'Check evidence bindings'}).click();
  await expect(page.getByText('The evidence does not match its recorded bindings.',{exact:true})).toBeVisible();
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  expect(writes).toEqual([]);expect(errors).toEqual([]);
});
