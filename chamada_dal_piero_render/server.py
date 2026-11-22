import os, re, time, secrets, json, threading, html
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from flask import Flask, request, jsonify, send_from_directory

BASE=Path(__file__).resolve().parent
app=Flask(__name__,static_folder=None)
app.config["MAX_CONTENT_LENGTH"]=16000
ROOMS={}
LOCK=threading.RLock()
LANG={"pt","es","en","it","de","zh-CN","zh-TW"}
MAX_ROOMS=300
def clean():
    now=time.time()
    for key in list(ROOMS):
        if now-ROOMS[key]["at"]>43200:
            del ROOMS[key]
def failure(message,status=400):
    return jsonify(error=message),status
@app.get("/")
@app.get("/chamada.html")
def page():
    return send_from_directory(BASE,"chamada.html")
@app.get("/icon.svg")
def icon():
    return send_from_directory(BASE,"icon.svg",mimetype="image/svg+xml")
@app.get("/manifest.webmanifest")
def manifest():
    return jsonify(name="Chamada Traduzida Dal Piero",short_name="Chamada Dal Piero",start_url="/chamada.html",scope="/",display="standalone",theme_color="#10223d",background_color="#10223d",icons=[{"src":"/icon.svg","sizes":"any","type":"image/svg+xml","purpose":"any maskable"}])
@app.get("/api/health")
def health():
    return jsonify(ok=True,app="Chamada Traduzida Dal Piero",experimental=True)
def access(d):
    code=str(d.get("room","")).upper()
    pid=str(d.get("pid",""))
    room=ROOMS.get(code)
    if not room or pid not in room["members"]:
        return None
    room["at"]=time.time()
    room["members"][pid]["seen"]=time.time()
    return room
@app.post("/api/join")
def join():
    d=request.get_json(silent=True) or {}
    if d.get("consent") is not True:return failure("É necessário aceitar o aviso de privacidade.")
    name=str(d.get("name","")).strip()[:55]
    src=d.get("src","pt");dst=d.get("listen","pt")
    if not name:return failure("Informe seu nome.")
    if src not in LANG or dst not in LANG:return failure("Idioma não disponível.")
    code=str(d.get("room","")).strip().upper()
    with LOCK:
        clean()
        if code:
            room=ROOMS.get(code)
            if room is None:return failure("Sala não encontrada. Solicite um novo convite.",404)
        else:
            if len(ROOMS)>=MAX_ROOMS:return failure("Limite temporário de salas atingido.",429)
            code=secrets.token_hex(4).upper()
            room={"messages":[],"members":{},"seq":0,"at":time.time(),"owner":None,"callStates":{},"callReplies":{}}
            ROOMS[code]=room
        if len(room["members"])>=24:return failure("Sala cheia.",429)
        pid=secrets.token_urlsafe(24)
        room["members"][pid]={"name":name,"src":src,"listen":dst,"seen":time.time(),"subject":"","acceptedFrom":0}
        if room.get("owner") is None:
            room["owner"]=pid
            room["callStates"][pid]="accepted"
        else:
            room["callStates"][pid]="pending"
    return jsonify(room=code,pid=pid,name=name,role="host" if room["owner"]==pid else "guest",callState=room["callStates"][pid])
@app.post("/api/call-action")
def call_action():
    d=request.get_json(silent=True) or {}
    action=d.get("action")
    if action not in ("accepted","rejected","hold","later"):
        return failure("Ação inválida.")
    target=str(d.get("target",""))
    reply=str(d.get("reply","")).strip()
    if len(reply)>650:return failure("Resposta muito longa.")
    if not reply:return failure("Selecione uma resposta.")
    with LOCK:
        room=access(d)
        if room is None:return failure("Sala inválida.",403)
        if room["owner"]!=d.get("pid"):return failure("Somente quem iniciou a chamada pode responder.",403)
        if target==room["owner"] or target not in room["members"]:
            return failure("Convidado não encontrado.",404)
        if action=="accepted" and room["callStates"].get(target)!="accepted":
            room["members"][target]["acceptedFrom"]=room["seq"]
        room["callStates"][target]=action
        room["callReplies"][target]=reply
    return jsonify(ok=True,callState=action,reply=reply)
@app.post("/api/call-subject")
def call_subject():
    d=request.get_json(silent=True) or {}
    subject=d.get("subject","")
    if not isinstance(subject,str) or len(subject)>350:return failure("Assunto inválido.")
    subject=subject.strip()
    if not subject:return failure("Informe o assunto da chamada.")
    with LOCK:
        room=access(d)
        if room is None:return failure("Sala inválida.",403)
        if room["owner"]==d.get("pid"):return failure("Esta opção é para convidados.",403)
        room["members"][d["pid"]]["subject"]=subject
    return jsonify(ok=True,subject=subject)
@app.post("/api/message")
def message():
    d=request.get_json(silent=True) or {}
    text=str(d.get("text","")).strip()[:480]
    if not text:return failure("Fala vazia.")
    if not isinstance(d.get("text"),str) or len(d["text"])>480:return failure("Texto muito longo.")
    with LOCK:
        room=access(d)
        if not room:return failure("Participante ou sala inválida.",403)
        pid=d["pid"]
        member=room["members"][pid]
        if room["callStates"].get(pid)!="accepted":return failure("A chamada ainda não foi aceita ou está em espera.",403)
        room["seq"]+=1
        item={"id":room["seq"],"text":text,"src":member["src"],"name":member["name"],"ts":int(time.time())}
        room["messages"].append(item)
        room["messages"]=room["messages"][-160:]
    return jsonify(ok=True,id=item["id"])
@app.get("/api/poll")
def poll():
    d=request.args
    try:since=max(0,int(d.get("since","0")))
    except ValueError:since=0
    with LOCK:
        room=access(d)
        if not room:return failure("Sala encerrada ou inválida.",403)
        pid=str(d["pid"])
        call_state=room["callStates"].get(pid,"pending")
        host=room["owner"]==pid
        incoming=[{"pid":other,"name":member["name"],"state":room["callStates"].get(other,"pending"),"subject":member.get("subject",""),"reply":room["callReplies"].get(other,"")} for other,member in room["members"].items() if other!=room["owner"] and room["callStates"].get(other) in ("pending","accepted","rejected","hold","later") and time.time()-member["seen"]<150] if host else []
        msgs=([m for m in room["messages"] if m["id"]>max(since,room["members"][pid].get("acceptedFrom",0))][-50:] if call_state=="accepted" else [])
        online=sum(time.time()-v["seen"]<45 and room["callStates"].get(k)=="accepted" for k,v in room["members"].items())
    return jsonify(messages=msgs,online=online,callState=call_state,callReply=room["callReplies"].get(pid,""),incoming=incoming,host=host)
@app.post("/api/translate")
def translate():
    d=request.get_json(silent=True) or {}
    text=d.get("text","");src=d.get("src","pt");dst=d.get("to","pt")
    if not isinstance(text,str) or not text or len(text)>480:return failure("Texto inválido.")
    if src not in LANG or dst not in LANG:return failure("Idioma inválido.")
    if src==dst:return jsonify(text=text,engine="Original")
    a="zh-CN" if src=="zh-TW" else src
    b="zh-CN" if dst=="zh-TW" else dst
    url="https://api.mymemory.translated.net/get?"+urlencode({"q":text,"langpair":a+"|"+b})
    try:
        req=Request(url,headers={"User-Agent":"DalPieroTranslatedCall/1.0"})
        with urlopen(req,timeout=9) as resp:
            result=json.load(resp)
        if int(result.get("responseStatus",0))!=200:raise ValueError("Serviço indisponível")
        translated=html.unescape(result.get("responseData",{}).get("translatedText","")).strip()
        if not translated:raise ValueError("Tradução vazia")
        return jsonify(text=translated,engine="MyMemory; tradução experimental")
    except Exception:
        return failure("O serviço de tradução está indisponível. Tente novamente.",503)
@app.get("/api/export")
def export_txt():
    with LOCK:
        room=access(request.args)
        if not room:return failure("Acesso inválido.",403)
        pid=request.args.get("pid","")
        if room["callStates"].get(pid)!="accepted":
            return failure("Transcrição disponível apenas para participantes autorizados.",403)
        since=room["members"][pid].get("acceptedFrom",0)
        rows=[m for m in room["messages"] if m["id"]>since]
    text="\n".join(time.strftime("%Y-%m-%d %H:%M:%S",time.gmtime(m["ts"]))+" UTC | "+m["name"]+": "+m["text"] for m in rows)
    from flask import Response
    return Response(text,mimetype="text/plain",headers={"Content-Disposition":"attachment; filename=chamada-dal-piero.txt"})
if __name__=="__main__":
    app.run(host=os.getenv("HOST","0.0.0.0"),port=int(os.getenv("PORT","10000")),threaded=True)
