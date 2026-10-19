#!/usr/bin/env python3
"""Create a non-executable reading copy from the frozen report's Markdown AST."""
from pathlib import Path
from html import escape
import json
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, LongTable, TableStyle

ROOT = Path(__file__).resolve().parents[1]
import argparse
p=argparse.ArgumentParser();p.add_argument('--report',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
a=p.parse_args();DAY=a.report.name[:10];OUT=a.output.resolve()
source=a.report.read_text()
metadata='；'.join(x.removeprefix('- ') for x in source.splitlines() if x.startswith(('- 覆盖期间：','- 截止时点：','- 采集版本：','- 市场数据：')))
cutoff=next(x.removeprefix('- 截止时点：') for x in source.splitlines() if x.startswith('- 截止时点：'))
OUT.parent.mkdir(parents=True, exist_ok=True)
if OUT.exists():
    raise FileExistsError(OUT)
pdfmetrics.registerFont(TTFont('WindText', '/System/Library/Fonts/STHeiti Light.ttc', subfontIndex=0))
pdfmetrics.registerFont(TTFont('WindBold', '/System/Library/Fonts/STHeiti Medium.ttc', subfontIndex=0))
pdfmetrics.registerFontFamily('WindText', normal='WindText', bold='WindBold')
BODY = ParagraphStyle('body', fontName='WindText', fontSize=10, leading=16,
                      wordWrap='CJK', spaceAfter=6, textColor=colors.HexColor('#172334'))
SMALL = ParagraphStyle('small', parent=BODY, fontSize=9, leading=14, spaceAfter=1)
HEAD = {i: ParagraphStyle('h'+str(i), parent=BODY, fontName='WindBold',
                         fontSize={1:20, 2:15, 3:12}.get(i,11),
                         leading={1:29, 2:23, 3:19}.get(i,17),
                         spaceBefore=13, spaceAfter=8, keepWithNext=True,
                         textColor=colors.HexColor('#1e5277')) for i in range(1,7)}


def inline(tokens):
    result = []
    for t in tokens or []:
        typ = t['type']
        if typ in {'text', 'escape'}:
            result.append(inline(t['tokens']) if t.get('tokens') else escape(t.get('text','')))
        elif typ == 'strong':
            result.append('<b>'+inline(t.get('tokens'))+'</b>')
        elif typ == 'em':
            result.append(inline(t.get('tokens')))
        elif typ == 'codespan':
            result.append(escape(t.get('text','')))
        elif typ == 'link':
            href = t['href']
            result.append('<link color="#175e97" href="'+escape(href,quote=True)+'">'+inline(t.get('tokens'))+'</link>')
        elif typ == 'br':
            result.append('<br/>')
        elif typ == 'image':
            result.append(escape(t.get('text','')))
        else:
            result.append(escape(t.get('text','')))
    return ''.join(result)


story = [Paragraph('周报静态阅读版',HEAD[2]),
         Paragraph(escape(metadata),BODY)]


def consume(tokens):
    for t in tokens:
        typ = t['type']
        if typ == 'heading':
            story.append(Paragraph(inline(t.get('tokens')), HEAD[t['depth']]))
        elif typ in {'paragraph','text'}:
            story.append(Paragraph(inline(t.get('tokens')) if t.get('tokens') else escape(t.get('text','')),BODY))
        elif typ == 'list':
            for i,item in enumerate(t['items']):
                prefix = str((t.get('start') or 1)+i)+'. ' if t.get('ordered') else '- '
                text = inline(item.get('tokens',[{}])[0].get('tokens',[]))
                if not text:
                    text = escape(item.get('text',''))
                story.append(Paragraph(prefix+text,BODY))
                for sub in item.get('tokens',[])[1:]:
                    if sub.get('type') == 'list':consume([sub])
        elif typ == 'table':
            labels = [inline(c.get('tokens')) for c in t['header']]
            for row in t['rows']:
                values = [inline(c.get('tokens')) for c in row]
                title = labels[0]+': '+values[0] if labels[0] == 'Edge ID' else values[0]
                story.append(Paragraph(title,HEAD[3]))
                pairs = [[Paragraph(labels[j],SMALL),Paragraph(values[j],SMALL)] for j in range(1,len(labels))]
                table = LongTable(pairs,colWidths=[116,407],hAlign='LEFT')
                table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),
                                           ('BACKGROUND',(0,0),(0,-1),colors.HexColor('#edf3f9')),
                                           ('LINEBELOW',(0,0),(-1,-1),0.35,colors.HexColor('#dce4ed')),
                                           ('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),
                                           ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
                story.extend([table,Spacer(1,7)])
        elif typ == 'blockquote':consume(t.get('tokens',[]))
        elif typ == 'code':story.append(Paragraph(escape(t.get('text','')).replace('\n','<br/>'),SMALL))


def page(canvas, doc):
    canvas.saveState();canvas.setFont('WindText',8);canvas.setFillColor(colors.HexColor('#64748b'))
    canvas.drawString(36,20,DAY+' 周报 | '+cutoff)
    canvas.drawRightString(A4[0]-36,20,str(doc.page));canvas.restoreState()


consume(json.loads((ROOT/'tmp/pdfs'/f'{DAY}_tokens.json').read_text()))
doc = SimpleDocTemplate(str(OUT),pagesize=A4,leftMargin=36,rightMargin=36,topMargin=30,bottomMargin=36,
                        title=DAY+' 周报',author='每周简报')
doc.build(story,onFirstPage=page,onLaterPages=page)
print(OUT)
