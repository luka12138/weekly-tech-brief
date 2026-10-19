import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
const require=createRequire(import.meta.url);
const {marked}=await import(pathToFileURL(process.env.MARKED_MODULE || require.resolve('marked')).href);

const root=path.resolve(import.meta.dirname,'..');
if (!process.argv[2]) throw new Error('Usage: node render_weekly_brief.mjs REPORT.md');
const reportPath=path.resolve(process.argv[2]);
const source=fs.readFileSync(reportPath,'utf8');
const day=path.basename(reportPath).slice(0,10);
const metadata=source.split('\n').filter(x=>/^-( 覆盖期间| 截止时点| 采集版本| 市场数据)：/.test(x)).map(x=>x.replace(/^- /,'')).join('；');
// GFM requires a blank separator after a table. Change only the display input.
const display=source.replace(/(\|[^\n]+\|)\n(RV20[^\n]*)/g,'$1\n\n$2')
  .replace(/([。！？])\*\*(?=\S)/g,'$1** ');
const style=fs.readFileSync(path.join(root,'assets/weekly_brief_desktop.css'),'utf8');
let body=marked.parse(display);
body=body.replace(/<h2>([0-7])\./g, '<h2 id="s$1">$1.');
body=body.replace(/<table>/g,'<div class="table-wrap" tabindex="0"><table>').replace(/<\/table>/g,'</table></div>');
const nav=['市场与假设','本周头条','判断速览','公司详情','产业链判断','催化与验证','图谱','核验范围'].map((x,i)=>`<a href="#s${i}">${i} ${x}</a>`).join('');
const html=`<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'"><title>${day} 每周简报</title><style>${style}</style></head><body><header><strong>每周科技巨头晨间简报</strong><p>${metadata}</p><div class="status">行情口径、实际样本及本期限制见第0节。<a href="../logs/${day}_wind_market_observations_manifest.json">取数诊断</a></div></header><nav aria-label="章节导航">${nav}</nav><main>${body}</main><footer>本地静态阅读版。与冻结Markdown同源；不含实时取数、后验评分或预测效果认证。</footer></body></html>`;
fs.writeFileSync(reportPath.replace(/\.md$/,'.html'),html);
fs.mkdirSync(path.join(root,'tmp/pdfs'),{recursive:true});
fs.writeFileSync(path.join(root,`tmp/pdfs/${day}_tokens.json`),JSON.stringify(marked.lexer(display),null,2));
console.log('HTML and PDF AST written; Markdown preserved.');
