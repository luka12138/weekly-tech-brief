const fs=require('node:fs'),crypto=require('node:crypto');
const date='2026-09-21',p=`logs/${date}_research_coverage.json`,c=JSON.parse(fs.readFileSync(p));
if(c.checks.length)throw Error('Selection already recorded; resume in place.');
const specs=[
 ['APL-O0','Apple','d02','company','https://www.apple.com/newsroom/','blocked','入口仅返回导航；随后通过官方归档及具体公告恢复。',['iPhone','服务']],
 ['APL-O','Apple','d03','company','https://www.apple.com/newsroom/archive/','reviewed','核读9月归档；Siri AI、软硬件上市及儿童保护列候选，旧9/9发布不重复。',['iPhone','服务','可穿戴设备']],
 ['APL-I','Apple','d04','media','https://www.investing.com/news/stock-market-news/musks-x-corp-and-spacexairesolve-antitrust-lawsuit-against-apple-4899830','reviewed','独立校准发现X/SpaceXAI诉讼解决；旧Siri集体诉讼不混同。',['iPhone','服务']],
 ['MS-O','Microsoft','d01','company','https://news.microsoft.com/source/view-all/','reviewed','9/15股息及政府套件，9/17芯片设计及转型文章；按重要性选资本回报和政府产品。',['Microsoft 365','Azure']],
 ['MS-I','Microsoft','d04','media','https://www.marketscreener.com/news/microsoft-drafts-code-of-conduct-to-keep-its-ai-under-human-control-ce785bdcdc8bf025','reviewed','独立轮次发现AI行为准则草案，不是成文法或能力安全认证。',['Azure','Microsoft 365']],
 ['GOO-O','Alphabet / Google','d02','company','https://blog.google/','reviewed','官方首页识别Live模型、Windows应用；后续d11/d14定位9/15和9/17版本。',['Gemini','Google Cloud']],
 ['GOO-I','Alphabet / Google','d04','media','https://ae.marketscreener.com/news/google-should-relax-ad-tech-rules-appoint-antitrust-monitor-us-judge-finds-ce785bd2d08ff121','reviewed','识别广告技术案本周救济细节；9/2不拆分初裁及搜索案须分别处理。',['搜索']],
 ['AWS-O','Amazon / AWS','d01','company','https://www.aboutamazon.com/news/company-news','reviewed','公司入口读到9/16公司近况及9/13货运事故更新；旧融资/芯片合同不重发。',['AWS','物流']],
 ['AWS-I','Amazon / AWS','d06','media','https://www.marketscreener.com/news/amazon-enters-ai-safety-fray-calls-for-rigorous-testing-safeguards-ce785bd3df89ff22','reviewed','独立轮次兼看21 Air事故、Prime退款程序及安全立场，发现Generac具日期申报；选择资本供应承诺及安全立场。',['AWS','物流','Prime']],
 ['META-O','Meta','d02','company','https://about.fb.com/news/','reviewed','9/15 Meta One与9/16 Threads工具；优先跨应用订阅，9/8 Muse不重新算发布。',['Meta AI','Instagram','Facebook','WhatsApp']],
 ['META-I','Meta','d08','media','https://www.marketscreener.com/news/meta-s-zuckerberg-says-ai-labs-have-enough-incentive-to-build-safely-ce785bd2d88bf521','reviewed','独立核验安全治理立场与法律责任语境，不把早前和解重计本周。',['Meta AI']],
 ['NV-O','NVIDIA','d03','company','https://nvidianews.nvidia.com/','reviewed','9/14 CUDA-Q、9/15能效、9/16 MLPerf及电网联盟；优先平台实测阶段，其余留资料池。',['数据中心 GPU','CUDA','AI 软件']],
 ['NV-I','NVIDIA','d08','media','https://finance.yahoo.com/technology/ai/articles/palantir-nvidia-curb-ai-model-151108619.html','reviewed','独立轮次发现模型使用与IP保护争议，须区分报道中的可能限制与已全面停用。',['AI 软件','数据中心 GPU']],
 ['TSLA-O','Tesla','d05','company','https://ir.tesla.com/','reviewed','官方IR当前财报止于Q2；不声称全部产品页或经营没有变化。',['电动车','FSD']],
 ['TSLA-I','Tesla','d06','media','https://www.marketscreener.com/news/us-agency-orders-tesla-to-answer-questions-on-cybercab-certification-ce785bddde80f524','reviewed','独立发现9/15认证答复要求，是旧调查程序增量；Roadster日期旧披露不重发。',['电动车','FSD']],
 ['OA-O','OpenAI','d05','company','https://openai.com/news/','reviewed','9/16失配披露、广告、价值度量，9/17法律产品及9/18澳洲蓝图；优先研究与核心产品使用条件。',['GPT 模型','ChatGPT','OpenAI API','AI 安全评估']],
 ['OA-I','OpenAI','d08','media','https://apnews.com/article/089e75b95bc935af092da7b79d92706d','reviewed','独立安全报道校准：六份披露不是六起本周事故；关注治理及潜在第三方影响。',['GPT 模型','AI 安全评估']],
 ['AN-O','Anthropic','d05','company','https://www.anthropic.com/news','reviewed','官方9/17前沿研发可观察指标；9/1模型和9/10威胁报告为旧闻。',['Claude 模型','AI 安全研究']],
 ['AN-I','Anthropic','d08','media','https://currently.att.yahoo.com/att/anthropic-accenture-invest-2-billion-210242461.html','reviewed','独立发现与Accenture评估承诺及未定模型发布；优先确认合作和研发透明度，不以IPO传闻填满五条。',['Claude 模型','AI 安全研究']],
 ['SS-O','Samsung Electronics','d07','company','https://news.samsung.com/global/category/press-release','reviewed','官方本周One UI 9、ISAC试验；优先用户AI软件扩面，设计展和区域营销不凑数。',['移动设备']],
 ['SS-I','Samsung Electronics','d10','media','https://ca.marketscreener.com/news/samsung-sk-hynix-reject-kepco-s-19-billion-power-prepayment-proposal-document-shows-ce785bdcd88bf72d','reviewed','独立发现电力预付提案遭拒；涉及资本安排而非确认停电或已支付款项。',['存储','晶圆代工']],
 ['SK-O','SK Hynix','v02','company','https://news.skhynix.com/en/fact-10/','reviewed','官网9/16回应Intel报道尚无确认计划；入口9/21论坛超截止不纳入。',['DRAM','NAND']],
 ['SK-I','SK Hynix','d09','media','https://ca.marketscreener.com/news/sk-hynix-in-talks-with-intel-about-deal-to-make-memory-chips-in-the-us-for-the-first-time-sources-s-ce785bd2d881f52c','reviewed','独立发现Intel洽谈、Solidigm NAND选址、工资协议，后续与官方回应及技术转移审查条件并读。',['DRAM','NAND','HBM']],
 ['TSM-O0','TSMC','d06','company','https://pr.tsmc.com/english/news','blocked','新闻入口Internal Error，已转官方IR及具日期单篇核读。',['晶圆服务']],
 ['TSM-O','TSMC','d12','company','https://investor.tsmc.com/english','reviewed','IR最近财务公告是8月营收，9/8 ASML原公告不重计；客户新品需定向核验。',['先进逻辑代工','N3/N2 节点']],
 ['TSM-I','TSMC','d13','media','https://kuwaittimes.com/article/49813/technology/mediatek-launches-new-mobile-chip-using-tsmc-tech/','reviewed','独立发现9/15 MediaTek客户2nm新品，选核实际产品发布，不以论坛传言推算产能。',['先进逻辑代工','N3/N2 节点']]
];
const records=[];
for(const [id,company,batch,family,url,status,note,businesses]of specs){const r=JSON.parse(fs.readFileSync(`logs/${date}_raw_${batch}.json`));if(!r.result)throw Error(batch);const t=typeof r.at==='string'?r.at:r.at.current_time;const at=t.replace(' UTC','Z').replace(' ','T');const ref=`logs/${date}_source_reviews.json#${id}`;c.checks.push({id,company,stage:family==='company'?'discovery':'countercheck',source_family:family,status,query_or_url:url,entrypoint:url,result_ref:ref,note,checked_at:at,businesses,categories:family==='media'?['legal','operations']:['product','capital'],candidate_ids:[]});records.push({id,checked_at:at,url,note,capture_sha256:crypto.createHash('sha256').update(fs.readFileSync(`logs/${date}_raw_${batch}.json`)).digest('hex'),raw_local_only:true});}
const choices=[
 ['APL-SIRI',['Apple','Alphabet / Google'],'Siri AI英文beta实际推出，保留地区/账号/用量限制',['APL-O','GOO-O']],['APL-STORE',['Apple'],'iPhone 18 Pro进入上市阶段，不能以活动照片推算销量',['APL-O']],['APL-X',['Apple'],'X/SpaceXAI诉苹果案解决，阶段及保留请求核验',['APL-I']],
 ['MS-CODE',['Microsoft'],'自研AI行为准则草案',['MS-I']],['MS-G7',['Microsoft'],'政府G7套件及开放条件',['MS-O']],['MS-DIV',['Microsoft'],'季度股息上调及支付登记日期',['MS-O']],
 ['GOO-LIVE',['Alphabet / Google'],'Gemini 3.8 Live系列及预览/订阅边界',['GOO-O']],['GOO-WIN',['Alphabet / Google'],'Gemini Windows应用分发',['GOO-O']],['GOO-ADS',['Alphabet / Google'],'广告技术案救济细节公开，不重报9/2不拆分结论',['GOO-I']],
 ['AWS-GEN',['Amazon / AWS'],'Generac后备发电机供货与附条件认股权证',['AWS-I']],['AWS-SAFETY',['Amazon / AWS'],'安全测试与发展节奏立场',['AWS-I']],
 ['META-ONE',['Meta'],'跨应用Meta One订阅与免费基本服务边界',['META-O']],['META-SAFETY',['Meta'],'扎克伯格安全治理立场',['META-I']],
 ['NV-MLPERF',['NVIDIA'],'Vera Rubin MLPerf推理测试，区分基准与收入',['NV-O']],['NV-IP',['NVIDIA'],'据报道模型使用限制与IP争议',['NV-I']],
 ['TSLA-CERT',['Tesla'],'Cybercab认证调查答复要求',['TSLA-I']],
 ['OA-MISALIGN',['OpenAI'],'失配报告框架及六份历史观察披露',['OA-O','OA-I']],['OA-LAW',['OpenAI'],'Astra for Law使用边界',['OA-O']],['OA-ADS',['OpenAI'],'广告AI产品新阶段',['OA-O']],
 ['AN-METRICS',['Anthropic'],'研发自主性与监督指标提议',['AN-O']],['AN-ACC',['Anthropic'],'Accenture独立评估五年投入承诺',['AN-I']],
 ['SS-UI',['Samsung Electronics'],'One UI 9扩面及设备地区限制',['SS-O']],['KR-POWER',['Samsung Electronics','SK Hynix'],'拒绝KEPCO电力预付提案的本周披露',['SS-I','SK-I']],
 ['SK-INTEL',['SK Hynix'],'Intel美国制造洽谈报道及公司尚无确认计划回应',['SK-I','SK-O']],['SK-NAND',['SK Hynix'],'Solidigm美国NAND厂选址讨论',['SK-I']],['SK-WAGE',['SK Hynix'],'韩国工会工资协议获批报道',['SK-I']],
 ['TSM-MTK',['TSMC'],'MediaTek客户2nm产品发布',['TSM-I']]
];
for(const [id,companies,summary,ids]of choices){c.candidates.push({id,companies,summary,discovered_by:ids,materiality:'material',materiality_reason:summary+'，可能影响产品采用、资本义务或经营风险。',disposition:'pending',reason:'已按重要性入选，尚待具体版本、时间及关键限制核证。',research:{event_key:id,canonical_id:id,member_ids:[id],identity_status:'identified',materials:[{role:'source_review',path:`logs/${date}_source_reviews.json`,locator:ids.join(',')}],open_questions:['核对来源正文版本、公开日期及关键限制'],next_action:{kind:'fetch_gap',target:id,question:'完成入选事实核证'}}});for(const check of c.checks)if(ids.includes(check.id))check.candidate_ids.push(id);}
c.selection_frozen_at=new Date().toISOString();c.selection_note='27项独立选题，29项公司展示；均少于五条，先冻结再深核。重要性相近但未选的普通迭代、旧闻、未定消息留资料池，不继续全量检索。入选不通过则缩限或如实撤回，不能造证。';
fs.writeFileSync(p,JSON.stringify(c,null,2)+'\n');fs.writeFileSync(`logs/${date}_source_reviews.json`,JSON.stringify({schema_version:1,records},null,2)+'\n');
console.log(JSON.stringify({checks:c.checks.length,candidates:c.candidates.length,frozen_at:c.selection_frozen_at}));
