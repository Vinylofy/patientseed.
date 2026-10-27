"""Robots rules for the additional bounded assessment, including wildcard paths."""
from __future__ import annotations
import re
from urllib.parse import unquote, urlsplit

AGENT='publiccatalogcollector/0.1'


def rules(text):
    groups=[];agents=[];paths=[];delay=0
    for line in text.splitlines():
        line=line.split('#',1)[0].strip()
        if ':' not in line:continue
        key,value=(part.strip() for part in line.split(':',1));key=key.casefold()
        if key=='user-agent':
            if paths or delay:
                groups.append((agents,paths,delay));agents=[];paths=[];delay=0
            agents.append(value.casefold())
        elif agents and key in {'allow','disallow'} and value:
            paths.append((value,key=='allow'))
        elif agents and key=='crawl-delay':
            try:delay=max(delay,float(value))
            except ValueError:pass
    if agents:groups.append((agents,paths,delay))
    matched=[]
    for agents,paths,delay in groups:
        specificity=max((0 if a=='*' else len(a) for a in agents if a=='*' or a in AGENT),default=-1)
        if specificity>=0:matched.append((specificity,paths,delay))
    best=max((v[0] for v in matched),default=-1)
    return [(p,allow) for rank,paths,_ in matched if rank==best for p,allow in paths],max(
        (delay for rank,_,delay in matched if rank==best),default=0)


def allowed(text,url):
    selected,_=rules(text)
    parts=urlsplit(url);path=unquote(parts.path or '/')+('?' + unquote(parts.query) if parts.query else '')
    matched=[]
    for pattern,allow in selected:
        pattern=unquote(pattern)
        ending=pattern.endswith('$');pattern=pattern[:-1] if ending else pattern
        expression='^'+re.escape(pattern).replace(r'\*','.*')+('$' if ending else '')
        if re.search(expression,path):matched.append((len(pattern.replace('*','')),allow))
    return max(matched,default=(0,True))[1]
