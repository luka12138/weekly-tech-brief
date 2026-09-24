const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const root=path.resolve(__dirname,'..'),date='2026-09-21',archive=`archives/${date}_before_production`;
const hash=p=>crypto.createHash('sha256').update(fs.readFileSync(path.join(root,p))).digest('hex');
const file=`logs/${date}_research_coverage.json`;
if(fs.existsSync(path.join(root,file)))throw Error('Resume existing coverage; do not overwrite.');
const paths=['state/supply_graph_baseline.json','state/product_relationships_2026.json','reports/2026-09-14_weekly_morning_brief.md'];
for(const p of paths){const d=path.join(root,archive,p);fs.mkdirSync(path.dirname(d),{recursive:true});fs.copyFileSync(path.join(root,p),d,fs.constants.COPYFILE_EXCL);}
const old=JSON.parse(fs.readFileSync(path.join(root,'logs/2026-09-14_research_coverage.json')));
const coverage={schema_version:1,workflow_version:2,selection_policy:'company_top5',report_date:date,cutoff_exclusive:date+'T00:00:00+08:00',status:'draft',run_started_at:'2026-09-21T01:12:29.642Z',checks:[],candidates:[],company_conclusions:{},watchlist:old.watchlist.filter(w=>w.status==='active').map(w=>({id:w.id,companies:w.companies,topic:w.topic,status:'active',review_scope:'not_selected',defer_reason:'本期有限筛选尚未完成，相关入选事项才继续核查。',note:'保留稳定ID与未决状态，不认证本周没有变化。'})),prior_report:{path:paths[2],sha256:hash(paths[2]),note:'9/14已发布报告仅作近况、事件身份与活跃事项对照，不是9/21新事实证据。'},baseline_start_hashes:Object.fromEntries(paths.map(p=>[p,hash(p)])),gaps:['本期筛选和入选核验尚未完成。']};
fs.writeFileSync(path.join(root,file),JSON.stringify(coverage,null,2)+'\n');
const rules=['.agents/skills/weekly-tech-brief/SKILL.md','docs/point_in_time_policy.md','docs/weekly_brief_template_v2.md','docs/verification_manual.md','docs/research_coverage.md','docs/task_consolidation.md','docs/context_efficiency.md','docs/tool_output_contract.md','docs/research_source_routes.md'];
fs.writeFileSync(path.join(root,`logs/${date}_run_state.json`),JSON.stringify({report_date:date,status:'research',started_at:coverage.run_started_at,rules:Object.fromEntries(rules.map(p=>[p,hash(p)])),archive,scope:'12 companies, 0-5 selected independent events; sequential current model; production only'},null,2)+'\n');
console.log(JSON.stringify({coverage:file,status:'draft',archive,watchlist:coverage.watchlist.length}));
