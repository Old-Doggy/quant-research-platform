"""List static chart rendering sites; this is an inventory, not runtime acceptance."""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path


RENDERERS={'plotly_chart','altair_chart','vega_lite_chart','line_chart','area_chart',
           'bar_chart','scatter_chart','pyplot','image','graphviz_chart',
           'render_interactive_chart'}


class ChartSites(ast.NodeVisitor):
    def __init__(self,path,source):
        self.path=path
        self.source=source
        self.scope=[]
        self.rows=[]

    def visit_FunctionDef(self,node):
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_AsyncFunctionDef=visit_FunctionDef

    def visit_Call(self,node):
        renderer=node.func.attr if isinstance(node.func,ast.Attribute) else node.func.id if isinstance(node.func,ast.Name) else ''
        # The legacy iframe renderer may contain a chart or another HTML widget.
        iframe=(isinstance(node.func,ast.Attribute) and isinstance(node.func.value,ast.Name)
                and node.func.value.id=='components' and renderer=='html')
        if renderer in RENDERERS or iframe:
            options={k.arg:ast.unparse(k.value) for k in node.keywords if k.arg}
            self.rows.append(dict(file=self.path,line=node.lineno,function='.'.join(self.scope),
                renderer=renderer,input=ast.unparse(node.args[0]) if node.args else None,
                key=options.get('key'),config=options.get('config'),on_select=options.get('on_select'),
                status='unreviewed_runtime',scope='static_site_not_chart_count'))
        self.generic_visit(node)


def inventory(root):
    rows=[]
    for path in sorted((root/'portfolio_app').glob('*.py')):
        source=path.read_text(encoding='utf-8-sig')
        scanner=ChartSites(path.relative_to(root).as_posix(),source)
        scanner.visit(ast.parse(source))
        rows.extend(sorted(scanner.rows,key=lambda r:r['line']))
    return rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    rows=inventory(Path(__file__).resolve().parents[1])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(dict(render_sites=len(rows),plotly=sum(r['renderer']=='plotly_chart' for r in rows),
        explicit_selection=sum(bool(r['on_select']) for r in rows)),ensure_ascii=False))


if __name__=='__main__':
    main()
