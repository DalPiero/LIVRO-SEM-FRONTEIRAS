import os, re, time, secrets, json, threading, html, ipaddress, asyncio
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from flask import Flask, request, jsonify, send_from_directory, Response

BASE=Path(__file__).resolve().parent
app=Flask(__name__,static_folder=None)
app.config["MAX_CONTENT_LENGTH"]=16000
ROOMS={}
LOCK=threading.RLock()
LANG={"pt","es","en","it","de","ru","zh-CN","zh-TW"}
MAX_ROOMS=300
PERMANENT_CODE="DALPIERO"
HOST_KEY_ENV="DALPIERO_HOST_KEY"
# Counters are aggregate and in memory. A free Render instance does not guarantee durable storage.
ACCESS_CHOICES=("financeira","educacional","digital","linguistica","social","reservada","teste","pagar")
ACCESS_COUNTS={key:0 for key in ACCESS_CHOICES}
ACCESS_COUNTS_STARTED=time.time()
@app.post("/api/access-choice")
def count_access_choice():
    payload=request.get_json(silent=True)
    choice=payload.get("choice") if isinstance(payload,dict) else None
    if choice not in ACCESS_COUNTS:
        return failure("Opção inválida.",400)
    with LOCK:
        ACCESS_COUNTS[choice]+=1
    return jsonify(ok=True)
@app.get("/api/access-stats")
def access_statistics():
    with LOCK:
        counts=dict(ACCESS_COUNTS)
    return jsonify(counts=counts,from_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime(ACCESS_COUNTS_STARTED)),persistence="memory",notice="Totais agregados desde a última reinicialização do serviço. Não são contagens de pessoas únicas.",cache_control="no-store")

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
@app.get("/app-icon-192.png")
def icon192():
    return send_from_directory(BASE,"app-icon-192.png",mimetype="image/png")
@app.get("/app-icon-512.png")
def icon512():
    return send_from_directory(BASE,"app-icon-512.png",mimetype="image/png")
@app.get("/manifest.webmanifest")
def manifest():
    from flask import Response
    content={"id":"/chamada.html?s=DALPIERO","name":"Chamada Traduzida Dal Piero","short_name":"Chamada Dal Piero","description":"Sala permanente de chamadas com tradução experimental.","start_url":"/chamada.html?s=DALPIERO","scope":"/","display":"standalone","background_color":"#10223d","theme_color":"#10223d","icons":[{"src":"/app-icon-192.png","sizes":"192x192","type":"image/png","purpose":"any"},{"src":"/app-icon-512.png","sizes":"512x512","type":"image/png","purpose":"any maskable"}]}
    return Response(json.dumps(content,ensure_ascii=False),mimetype="application/manifest+json")

# Language greeting is based on an approximate public IP country, never on precise GPS.
# Only the country code is returned to the browser; the IP is not persisted here.
COUNTRY_LANG = {
    "BR":"pt", "PT":"pt", "AO":"pt", "MZ":"pt", "CV":"pt",
    "ES":"es", "MX":"es", "AR":"es", "CO":"es", "CL":"es", "PE":"es",
    "UY":"es", "PY":"es", "EC":"es", "BO":"es", "VE":"es", "CR":"es",
    "PA":"es", "CU":"es", "DO":"es", "GT":"es", "HN":"es", "NI":"es",
    "SV":"es", "PR":"es",
    "FR":"fr", "BE":"fr", "LU":"fr", "MC":"fr",
    "IT":"it", "SM":"it", "VA":"it",
    "DE":"de", "AT":"de", "CH":"de", "LI":"de",
    "CN":"zh-CN", "TW":"zh-TW", "HK":"zh-TW", "MO":"zh-TW",
    "JP":"ja", "KR":"ko", "RU":"ru", "UA":"uk",
    "NL":"nl", "TR":"tr", "PL":"pl", "ID":"id",
    "VN":"vi", "TH":"th", "IN":"hi", "BD":"bn",
    "SA":"ar", "AE":"ar", "EG":"ar", "MA":"ar",
    "DZ":"ar", "TN":"ar", "QA":"ar", "KW":"ar", "JO":"ar",
    "IL":"he", "IR":"fa", "KE":"sw", "TZ":"sw"
}
def public_client_ip():
    # Forwarded IP is a best-effort hint behind Render's reverse proxy.
    # It is used only for greeting language, never for access control.
    forwarded=request.headers.get("X-Forwarded-For","")
    candidates=[part.strip() for part in forwarded.split(",")[:5]]
    candidates.append(request.remote_addr or "")
    for value in candidates:
        try:
            ip=ipaddress.ip_address(value)
            if ip.is_global:
                return str(ip)
        except ValueError:
            continue
    return None

@app.get("/api/greeting-language")
def greeting_language():
    country=""
    provider_headers=("CF-IPCountry","X-Vercel-IP-Country","CloudFront-Viewer-Country")
    for name in provider_headers:
        candidate=request.headers.get(name,"").strip().upper()
        if len(candidate)==2 and candidate.isalpha():
            country=candidate
            break
    if not country:
        ip=public_client_ip()
        if ip:
            try:
                req=Request("https://ipwho.is/"+ip+"?fields=success,country_code",
                            headers={"User-Agent":"ChamadaDalPiero/1.1"})
                with urlopen(req,timeout=2.5) as response:
                    payload=json.load(response)
                if payload.get("success") and re.fullmatch(r"[A-Z]{2}",payload.get("country_code","")):
                    country=payload["country_code"]
            except Exception:
                pass
    if not country:
        return jsonify(language=None,country=None,source="browser",supported=False)
    lang=COUNTRY_LANG.get(country,"en")
    return jsonify(language=lang,country=country,source="ip",supported=True)

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
    permanent=code==PERMANENT_CODE
    wants_host=d.get("role")=="host"
    if wants_host and not permanent:return failure("O acesso de responsável é exclusivo da sala permanente.",403)
    if permanent and wants_host:
        expected=os.getenv(HOST_KEY_ENV,"")
        supplied=str(d.get("hostKey",""))
        if not expected or not secrets.compare_digest(supplied,expected):
            return failure("Código reservado ao responsável incorreto.",403)
    with LOCK:
        clean()
        if code:
            room=ROOMS.get(code)
            if room is None:
                if not permanent:return failure("Sala não encontrada. Solicite um novo convite.",404)
                room={"messages":[],"members":{},"seq":0,"at":time.time(),"owner":None,"callStates":{},"callReplies":{}}
                ROOMS[code]=room
        else:
            if len(ROOMS)>=MAX_ROOMS:return failure("Limite temporário de salas atingido.",429)
            code=secrets.token_hex(4).upper()
            room={"messages":[],"members":{},"seq":0,"at":time.time(),"owner":None,"callStates":{},"callReplies":{}}
            ROOMS[code]=room
        if permanent:
            stale=[key for key,item in room["members"].items() if time.time()-item["seen"]>1800]
            for key in stale:
                room["members"].pop(key,None)
                room["callStates"].pop(key,None)
                room["callReplies"].pop(key,None)
            if room["owner"] not in room["members"]:room["owner"]=None
        if len(room["members"])>=24:return failure("Sala cheia.",429)
        pid=secrets.token_urlsafe(24)
        room["members"][pid]={"name":name,"src":src,"listen":dst,"seen":time.time(),"subject":"","acceptedFrom":0}
        if permanent:
            if wants_host:
                old=room.get("owner")
                if old and old in room["members"]:
                    room["callStates"][old]="later"
                    room["callReplies"][old]="O responsável assumiu a sala em outro dispositivo."
                room["owner"]=pid
                room["callStates"][pid]="accepted"
                room["members"][pid]["acceptedFrom"]=room["seq"]
            else:
                room["callStates"][pid]="pending"
        elif room.get("owner") is None:
            room["owner"]=pid
            room["callStates"][pid]="accepted"
        else:
            room["callStates"][pid]="pending"
    return jsonify(room=code,pid=pid,name=name,permanent=permanent,role="host" if room["owner"]==pid else "guest",callState=room["callStates"][pid])
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
        item={"id":room["seq"],"pid":pid,"text":text,"src":member["src"],"name":member["name"],"ts":int(time.time())}
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
        participants=([{"name":v["name"],"speak":v["src"],"listen":v["listen"],"online":time.time()-v["seen"]<45,"host":k==room["owner"]} for k,v in room["members"].items() if room["callStates"].get(k)=="accepted" and time.time()-v["seen"]<180] if call_state=="accepted" else [])
    return jsonify(messages=msgs,online=online,participants=participants,callState=call_state,callReply=room["callReplies"].get(pid,""),incoming=incoming,host=host)
# Experimental one-to-few live WebRTC signaling. No media or SDP is stored on disk.
# Signaling is only accessible to authorized members of the same in-memory room.
LIVE_SIGNALS_MAX=400
LIVE_VIEWERS_MAX=5
@app.post("/api/live/control")
def live_control():
    d=request.get_json(silent=True) or {}
    language=d.get("language","en")
    active=d.get("active")
    if type(active) is not bool or language not in LANG:
        return failure("Configuração de transmissão inválida.")
    with LOCK:
        room=access(d)
        if not room or room["owner"]!=str(d.get("pid","")):
            return failure("Somente o responsável pode iniciar o vídeo ao vivo.",403)
        if room["callStates"].get(str(d["pid"]))!="accepted":
            return failure("Responsável não autorizado.",403)
        room["live"]={"active":active,"language":language,"host":str(d["pid"]),"startedAt":int(time.time()) if active else 0}
        room["signals"]=[]
        room["signalSeq"]=0
        if active:
            room["liveViewers"]={}
        else:
            room.pop("liveViewers",None)
        state=room["live"].copy()
    return jsonify(ok=True,live=state)

@app.post("/api/live/signal")
def live_signal():
    d=request.get_json(silent=True) or {}
    target=str(d.get("to",""))
    kind=d.get("kind","")
    payload=d.get("payload",{})
    if kind not in ("watch","offer","answer","ice","bye"):
        return failure("Tipo de sinal inválido.")
    if not isinstance(payload,dict) or len(json.dumps(payload,ensure_ascii=False))>18000:
        return failure("Sinal de mídia muito grande ou inválido.")
    with LOCK:
        room=access(d)
        sender=str(d.get("pid",""))
        if not room or room["callStates"].get(sender)!="accepted":
            return failure("Participante não autorizado.",403)
        live=room.get("live") or {}
        if not live.get("active") or live.get("host")!=room.get("owner"):
            return failure("Não existe transmissão ao vivo ativa.",409)
        if target not in room["members"] or room["callStates"].get(target)!="accepted" or sender==target:
            return failure("Destinatário não autorizado.",403)
        host=room["owner"]
        if kind=="watch":
            if sender==host or target!=host:return failure("Solicitação de plateia inválida.",403)
            viewers=room.setdefault("liveViewers",{})
            now=time.time()
            viewers={k:v for k,v in viewers.items() if now-v<45}
            room["liveViewers"]=viewers
            if sender not in viewers and len(viewers)>=LIVE_VIEWERS_MAX:
                return failure("Limite experimental de cinco espectadores simultâneos.",429)
            viewers[sender]=now
        elif kind=="offer":
            if sender!=host or target not in room.get("liveViewers",{}):
                return failure("Somente o palestrante pode ofertar vídeo a espectadores ativos.",403)
        elif kind in ("answer","ice","bye"):
            if sender!=host and target!=host:return failure("Sinal deve envolver o palestrante.",403)
            if sender!=host and sender not in room.get("liveViewers",{}):
                return failure("Espectador não registrado.",403)
        room["signalSeq"]=room.get("signalSeq",0)+1
        item={"id":room["signalSeq"],"from":sender,"to":target,"kind":kind,"payload":payload}
        room.setdefault("signals",[]).append(item)
        room["signals"]=room["signals"][-LIVE_SIGNALS_MAX:]
    return jsonify(ok=True,id=item["id"])

@app.get("/api/live/poll")
def live_poll():
    try:since=max(0,int(request.args.get("since",0)))
    except (ValueError,TypeError):since=0
    with LOCK:
        room=access(request.args)
        pid=str(request.args.get("pid",""))
        if not room or room["callStates"].get(pid)!="accepted":
            return failure("Participante não autorizado.",403)
        live=room.get("live") or {"active":False,"language":"en"}
        signals=[{k:v for k,v in x.items() if k!="to"} for x in room.get("signals",[]) if x["to"]==pid and x["id"]>since][-80:]
        latest=room.get("signalSeq",0)
        if pid!=room.get("owner") and pid in room.get("liveViewers",{}):
            room["liveViewers"][pid]=time.time()
    return jsonify(live=live,signals=signals,latest=latest)

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
# On-demand neural narration for short, user-approved film-caption segments.
# Processing is temporary: raw text and generated MP3 are not saved to disk.
TTS_VOICES={
    "pt":"pt-BR-FranciscaNeural", "en":"en-US-AriaNeural",
    "es":"es-ES-ElviraNeural", "it":"it-IT-ElsaNeural",
    "de":"de-DE-KatjaNeural", "ru":"ru-RU-SvetlanaNeural",
    "zh-CN":"zh-CN-XiaoxiaoNeural", "zh-TW":"zh-TW-HsiaoChenNeural"
}
TTS_GATE=threading.BoundedSemaphore(2)
TTS_TIMES=[]
@app.post("/api/film-voice")
def film_voice():
    d=request.get_json(silent=True) or {}
    phrase=d.get("text","")
    target=d.get("language","pt")
    if not isinstance(phrase,str) or not 1<=len(phrase.strip())<=250:
        return failure("Cada narração deve conter de 1 a 250 caracteres.")
    if target not in TTS_VOICES:
        return failure("Idioma de narração não disponível.")
    if not TTS_GATE.acquire(blocking=False):
        return failure("Serviço de narração ocupado. Tente novamente.",429)
    try:
        with LOCK:
            now=time.monotonic()
            TTS_TIMES[:]=[x for x in TTS_TIMES if now-x<60]
            if len(TTS_TIMES)>=30:
                return failure("Limite temporário de narrações atingido. Tente novamente.",429)
            TTS_TIMES.append(now)
        try:
            import edge_tts
            async def generate():
                voice=edge_tts.Communicate(phrase.strip(),TTS_VOICES[target])
                chunks=[]
                async for item in voice.stream():
                    if item.get("type")=="audio":
                        chunks.append(item["data"])
                        if sum(map(len,chunks))>1_500_000:
                            raise ValueError("Arquivo de voz muito grande")
                return b"".join(chunks)
            audio=asyncio.run(asyncio.wait_for(generate(),timeout=24))
            if not audio:return failure("O serviço de voz não produziu áudio.",503)
            return Response(audio,mimetype="audio/mpeg",headers={"Cache-Control":"no-store","X-Content-Type-Options":"nosniff"})
        except Exception:
            return failure("Serviço externo de voz indisponível. Preserve as legendas e tente novamente.",503)
    finally:
        TTS_GATE.release()

@app.route("/api/export",methods=["GET","POST"])
def export_txt():
    data=request.get_json(silent=True) if request.method=="POST" else request.args
    if data is None:data={}
    with LOCK:
        room=access(data)
        if not room:return failure("Acesso inválido.",403)
        pid=data.get("pid","")
        if room["callStates"].get(pid)!="accepted":
            return failure("Transcrição disponível apenas para participantes autorizados.",403)
        since=room["members"][pid].get("acceptedFrom",0)
        rows=[m for m in room["messages"] if m["id"]>since]
    text="\n".join(time.strftime("%Y-%m-%d %H:%M:%S",time.gmtime(m["ts"]))+" UTC | "+m["name"]+": "+m["text"] for m in rows)
    from flask import Response
    return Response(text,mimetype="text/plain",headers={"Content-Disposition":"attachment; filename=chamada-dal-piero.txt"})
if __name__=="__main__":
    app.run(host=os.getenv("HOST","0.0.0.0"),port=int(os.getenv("PORT","10000")),threaded=True)
