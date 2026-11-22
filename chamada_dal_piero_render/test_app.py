"""Automated HTTP tests for the isolated Chamada Dal Piero backend."""
import unittest
from server import app, ROOMS

class CallTests(unittest.TestCase):
    def setUp(self):
        ROOMS.clear()
        self.client=app.test_client()

    def join(self,name,room=""):
        response=self.client.post("/api/join",json={"name":name,"room":room,"src":"pt","listen":"en","consent":True})
        self.assertEqual(response.status_code,200,response.json)
        return response.json

    def test_pwa_manifest_and_mobile_icons(self):
        import struct
        home=self.client.get("/chamada.html")
        self.assertEqual(home.status_code,200)
        html=home.get_data(as_text=True)
        self.assertIn('id="installBtn"',html)
        self.assertIn('id="installSteps"',html)
        self.assertIn('max-width:350px',html)
        self.assertIn('max-width:480px',html)
        manifest_response=self.client.get("/manifest.webmanifest")
        self.assertEqual(manifest_response.status_code,200)
        self.assertIn("application/manifest+json",manifest_response.mimetype)
        data=manifest_response.get_json()
        self.assertEqual(data["start_url"],"/chamada.html?s=DALPIERO")
        self.assertEqual(data["display"],"standalone")
        self.assertEqual([icon["sizes"] for icon in data["icons"]],["192x192","512x512"])
        for size in (192,512):
            response=self.client.get(f"/app-icon-{size}.png")
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.mimetype,"image/png")
            raw=response.data
            self.assertEqual(raw[:8],b"\x89PNG\r\n\x1a\n")
            self.assertEqual(struct.unpack(">II",raw[16:24]),(size,size))

    def test_language_choices_are_easy_to_find_and_unique(self):
        response=self.client.get("/chamada.html")
        self.assertEqual(response.status_code,200)
        page=response.get_data(as_text=True)
        self.assertEqual(page.count('id="src"'),1)
        self.assertEqual(page.count('id="listen"'),1)
        self.assertLess(page.index('id="languageQuick"'),page.index('id="installPanel"'))
        self.assertLess(page.index('id="languageQuick"'),page.index('id="enter"'))
        self.assertIn("language-fields",page)
        self.assertIn("updateLanguageFeedback",page)
        self.assertIn('state.joined=true;$("src").disabled=true;',page)

    def test_presential_recording_and_voice_controls(self):
        page=self.client.get("/chamada.html")
        self.assertEqual(page.status_code,200)
        markup=page.get_data(as_text=True)
        for element in ("recordingStudio","recordMode","recordCamera","recordConsent","recordStart","recordPause","recordStop","recordDownload","recordPreview","recordPhoto","recordPlayback","recordAudioPlayback","speechRate","treatment"):
            self.assertEqual(markup.count('id="'+element+'"'),1,element)
        self.assertIn("navigator.mediaDevices.getUserMedia",markup)
        self.assertIn("new MediaRecorder",markup)
        self.assertIn("recordConsent",markup)
        self.assertIn('recorder.start(1000)',markup)
        self.assertIn('recordStudio' if False else 'finaliseRecording',markup)
        self.assertIn('URL.createObjectURL(recorderStudio.blob)',markup)
        self.assertNotIn('fetch("/api/record',markup)
        self.assertIn("Local",markup) if False else None
        self.assertIn("max-width:380px",markup)
        self.assertIn('option value="neutral">Sem preferência de gênero',markup)

    def test_meeting_and_film_modes_are_accessible(self):
        page=self.client.get("/chamada.html").get_data(as_text=True)
        for element in ("modeSelector","meetingMode","filmMode","meetingGuide","meetingCopyInvite","meetingGo",
                        "filmCaptionPanel","filmSourceLanguage","filmCaptionLanguage","filmSpeaker",
                        "filmCaptionText","filmAddCaption","filmStartRecognition","filmStopRecognition",
                        "filmTranslateCaptions","filmSaveSrt","filmSaveVtt","filmSaveTxt","filmPreviewCaptions",
                        "filmCaptionStatus","filmCaptionList"):
            self.assertEqual(page.count('id="'+element+'"'),1,element)
        self.assertIn("WEBVTT",page)
        self.assertIn('cueTime(cue.start*1000,srt)',page)
        self.assertIn('recorderStudio.cues',page)
        self.assertIn("api(\"/api/translate\"",page)
        self.assertIn("stopFilmRecognition()",page)
        self.assertIn("navigator.mediaDevices.getUserMedia",page)
        self.assertIn("Cada pessoa escuta em seu idioma",page)

    def test_six_meeting_participants_keep_independent_languages(self):
        from unittest.mock import patch
        with patch.dict("os.environ",{"DALPIERO_HOST_KEY":"MeetingTestKey"},clear=False):
            host=self.client.post("/api/join",json={"name":"Professor","room":"DALPIERO","role":"host",
                "hostKey":"MeetingTestKey","src":"pt","listen":"pt","consent":True})
            self.assertEqual(host.status_code,200,host.json)
            hp=host.json["pid"]
            chosen=[("it","it"),("es","es"),("en","en"),("de","de"),("zh-CN","zh-CN")]
            for i,(src,dst) in enumerate(chosen):
                guest=self.client.post("/api/join",json={"name":"Pessoa "+str(i),"room":"DALPIERO",
                    "src":src,"listen":dst,"consent":True})
                self.assertEqual(guest.status_code,200,guest.json)
                pid=guest.json["pid"]
                accepted=self.client.post("/api/call-action",json={"room":"DALPIERO","pid":hp,"target":pid,
                    "action":"accepted","reply":"Bem-vindo"})
                self.assertEqual(accepted.status_code,200,accepted.json)
                statement=self.client.post("/api/message",json={"room":"DALPIERO","pid":pid,"text":"Olá "+src})
                self.assertEqual(statement.status_code,200,statement.json)
            got=self.client.get("/api/poll",query_string={"room":"DALPIERO","pid":hp,"since":0}).json
            self.assertEqual(len(got["messages"]),5)
            self.assertEqual([x["src"] for x in got["messages"]],[x[0] for x in chosen])

    def test_dub_create_button_clickable_and_local_import(self):
        page=self.client.get("/chamada.html").get_data(as_text=True)
        self.assertIn('<button id="filmDubCreate" type="button" class="green">',page)
        self.assertNotIn('<button id="filmDubCreate" type="button" class="green" disabled>',page)
        self.assertEqual(page.count('id="filmUpload"'),1)
        self.assertIn('file.type.startsWith("video/")',page)
        self.assertIn('recorderStudio.blob=file',page)
        self.assertIn('dubStatus("📝 Falta uma legenda.',page)
        self.assertIn('dubStatus("📹 Primeiro grave',page)
        self.assertIn('$("filmDubCreate").disabled=busy;',page)

    def test_film_dubbing_ui_and_russian_translation_support(self):
        markup=self.client.get("/chamada.html").get_data(as_text=True)
        for element in ("filmDubPanel","filmDubLanguage","filmDubMix","filmDubCreate","filmDubSave",
                        "filmDubStop","filmDubStatus","filmDubPreview"):
            self.assertEqual(markup.count('id="'+element+'"'),1,element)
        self.assertIn("canvas.captureStream(20)",markup)
        self.assertIn("createMediaStreamDestination",markup)
        self.assertIn('"/api/film-voice"',markup)
        self.assertIn('"ru":"Russo"',markup)
        self.assertIn('option value="ru"',markup)
        self.assertEqual(self.client.post("/api/translate",json={"text":"Привет", "src":"ru", "to":"ru"}).json["text"],"Привет")

    def test_film_voice_validation_and_short_synthesized_mp3(self):
        import sys
        from unittest.mock import patch
        from types import SimpleNamespace
        from server import TTS_TIMES
        TTS_TIMES.clear()
        self.assertEqual(self.client.post("/api/film-voice",json={"text":"","language":"pt"}).status_code,400)
        self.assertEqual(self.client.post("/api/film-voice",json={"text":"Bom dia","language":"xx"}).status_code,400)
        self.assertEqual(self.client.post("/api/film-voice",json={"text":"x"*251,"language":"pt"}).status_code,400)
        calls=[]
        class DummySpeech:
            def __init__(self,text,voice):calls.append((text,voice))
            async def stream(self):
                yield {"type":"audio","data":b"ID3-synth-audio"}
        with patch.dict(sys.modules,{"edge_tts":SimpleNamespace(Communicate=DummySpeech)}):
            answer=self.client.post("/api/film-voice",json={"text":"Hello","language":"en"})
            self.assertEqual(answer.status_code,200,answer.get_data(as_text=True))
            self.assertEqual(answer.mimetype,"audio/mpeg")
            self.assertEqual(answer.data,b"ID3-synth-audio")
            self.assertEqual(calls,[("Hello","en-US-AriaNeural")])
        TTS_TIMES.clear()

    def test_health(self):
        self.assertTrue(self.client.get("/api/health").json["ok"])

    def test_call_lifecycle_and_privacy(self):
        host=self.join("Anfitriao")
        key=host["room"]
        guest=self.join("Convidado",key)
        self.assertEqual(guest["callState"],"pending")
        self.assertEqual(self.client.post("/api/message",json={"room":key,"pid":guest["pid"],"text":"Antes"}).status_code,403)
        self.assertEqual(self.client.post("/api/export",json={"room":key,"pid":guest["pid"]}).status_code,403)
        self.assertEqual(self.client.post("/api/call-action",json={"room":key,"pid":guest["pid"],"target":host["pid"],"action":"accepted","reply":"ok"}).status_code,403)
        self.assertEqual(self.client.post("/api/message",json={"room":key,"pid":host["pid"],"text":"Private before entry"}).status_code,200)
        self.assertEqual(self.client.post("/api/call-subject",json={"room":key,"pid":guest["pid"],"subject":"Assunto de pesquisa"}).status_code,200)
        poll=self.client.get("/api/poll",query_string={"room":key,"pid":host["pid"],"since":0}).json
        self.assertEqual(poll["incoming"][0]["subject"],"Assunto de pesquisa")
        self.assertEqual(poll["incoming"][0]["state"],"pending")
        base={"room":key,"pid":host["pid"],"target":guest["pid"]}
        self.assertEqual(self.client.post("/api/call-action",json={**base,"action":"rejected","reply":"Agora nao"}).status_code,200)
        self.assertEqual(self.client.get("/api/poll",query_string={"room":key,"pid":host["pid"],"since":0}).json["incoming"][0]["state"],"rejected")
        self.assertEqual(self.client.get("/api/poll",query_string={"room":key,"pid":guest["pid"],"since":0}).json["callReply"],"Agora nao")
        self.assertEqual(self.client.post("/api/call-action",json={**base,"action":"accepted","reply":"Pode entrar"}).status_code,200)
        self.assertEqual(self.client.get("/api/poll",query_string={"room":key,"pid":guest["pid"],"since":0}).json["messages"],[])
        self.assertEqual(self.client.post("/api/message",json={"room":key,"pid":guest["pid"],"text":"Depois"}).status_code,200)
        got=self.client.get("/api/poll",query_string={"room":key,"pid":host["pid"],"since":0}).json["messages"]
        self.assertEqual(got[-1]["text"],"Depois")
        self.assertEqual(got[-1]["pid"],guest["pid"])
        self.assertNotIn("Private before entry",self.client.post("/api/export",json={"room":key,"pid":guest["pid"]}).get_data(as_text=True))
        self.assertEqual(self.client.post("/api/call-action",json={**base,"action":"hold","reply":"Aguarde 20 minutos"}).status_code,200)
        self.assertEqual(self.client.post("/api/message",json={"room":key,"pid":guest["pid"],"text":"Bloqueado"}).status_code,403)

    def test_permanent_room_host_and_guest(self):
        from unittest.mock import patch
        with patch.dict("os.environ", {"DALPIERO_HOST_KEY":"TestHostSecret",}, clear=False):
            public={"name":"Visitante","room":"DALPIERO","src":"pt","listen":"es","consent":True}
            guest=self.client.post("/api/join",json=public)
            self.assertEqual(guest.status_code,200,guest.json)
            g=guest.json
            self.assertEqual(g["role"],"guest")
            self.assertEqual(g["callState"],"pending")
            self.assertEqual(self.client.post("/api/call-action",json={"room":"DALPIERO","pid":g["pid"],"target":"invalid","action":"accepted","reply":"Aceito"}).status_code,403)
            wrong=self.client.post("/api/join",json={**public,"role":"host","hostKey":"incorrect"})
            self.assertEqual(wrong.status_code,403)
            owner=self.client.post("/api/join",json={**public,"name":"Professor","role":"host","hostKey":"TestHostSecret"})
            self.assertEqual(owner.status_code,200,owner.json)
            o=owner.json
            self.assertEqual(o["role"],"host")
            rows=self.client.get("/api/poll",query_string={"room":"DALPIERO","pid":o["pid"],"since":0}).json["incoming"]
            self.assertEqual(rows[0]["pid"],g["pid"])
            resp=self.client.post("/api/call-action",json={"room":"DALPIERO","pid":o["pid"],"target":g["pid"],"action":"accepted","reply":"Pode entrar"})
            self.assertEqual(resp.status_code,200,resp.json)
            self.assertEqual(self.client.post("/api/message",json={"room":"DALPIERO","pid":g["pid"],"text":"Mensagem autorizada"}).status_code,200)
            new_owner=self.client.post("/api/join",json={**public,"name":"Professor 2","role":"host","hostKey":"TestHostSecret"})
            self.assertEqual(new_owner.status_code,200,new_owner.json)
            old_poll=self.client.get("/api/poll",query_string={"room":"DALPIERO","pid":o["pid"],"since":0}).json
            self.assertEqual(old_poll["host"],False)
            self.assertEqual(old_poll["callState"],"later")
            self.assertEqual(self.client.post("/api/call-action",json={"room":"DALPIERO","pid":o["pid"],"target":g["pid"],"action":"rejected","reply":"Nao"}).status_code,403)

    def test_greeting_by_country_header_and_fallback(self):
        from unittest.mock import patch
        from server import public_client_ip
        with patch("server.urlopen") as blocked:
            response=self.client.get("/api/greeting-language",headers={"CF-IPCountry":"BR"})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json["language"],"pt")
            self.assertEqual(response.json["source"],"ip")
            blocked.assert_not_called()
        response=self.client.get("/api/greeting-language",headers={"CF-IPCountry":"ES"})
        self.assertEqual(response.json["language"],"es")
        response=self.client.get("/api/greeting-language",headers={"CF-IPCountry":"FR"})
        self.assertEqual(response.json["language"],"fr")
        response=self.client.get("/api/greeting-language",headers={"CF-IPCountry":"ZZ"})
        self.assertEqual(response.json["language"],"en")
        with patch("server.public_client_ip",return_value=None):
            response=self.client.get("/api/greeting-language")
            self.assertEqual(response.status_code,200)
            self.assertIsNone(response.json["language"])
            self.assertEqual(response.json["source"],"browser")

    def test_greeting_ip_lookup_when_country_header_unavailable(self):
        from unittest.mock import patch
        from io import BytesIO
        payload=BytesIO(b'{"success":true,"country_code":"AR"}')
        class MockResponse:
            def __enter__(self):return payload
            def __exit__(self,*args):return False
        with patch("server.public_client_ip",return_value="8.8.8.8"), patch("server.urlopen",return_value=MockResponse()) as lookup:
            response=self.client.get("/api/greeting-language")
            self.assertEqual(response.json["language"],"es")
            self.assertEqual(response.json["country"],"AR")
            lookup.assert_called_once()

    def test_italian_to_portuguese_call_flow(self):
        from unittest.mock import patch
        from io import BytesIO
        with patch.dict("os.environ",{"DALPIERO_HOST_KEY":"SampleSecret"},clear=False):
            host=self.client.post("/api/join",json={"name":"Responsavel","room":"DALPIERO","role":"host","hostKey":"SampleSecret","src":"pt","listen":"pt","consent":True}).json
            phone=self.client.post("/api/join",json={"name":"Visitante italiano","room":"DALPIERO","src":"it","listen":"it","consent":True}).json
            self.assertEqual(phone["callState"],"pending")
            action=self.client.post("/api/call-action",json={"room":"DALPIERO","pid":host["pid"],"target":phone["pid"],"action":"accepted","reply":"Chamada autorizada"})
            self.assertEqual(action.status_code,200)
            spoken=self.client.post("/api/message",json={"room":"DALPIERO","pid":phone["pid"],"text":"Buongiorno, professore."})
            self.assertEqual(spoken.status_code,200)
            received=self.client.get("/api/poll",query_string={"room":"DALPIERO","pid":host["pid"],"since":0}).json
            self.assertEqual(received["messages"][0]["src"],"it")
            self.assertEqual(received["messages"][0]["text"],"Buongiorno, professore.")
            self.assertEqual(received["messages"][0]["pid"],phone["pid"])
            class Translation:
                def __enter__(self):return BytesIO(b'{"responseStatus":200,"responseData":{"translatedText":"Bom dia, professor."}}')
                def __exit__(self,*args):return False
            with patch("server.urlopen",return_value=Translation()) as translated:
                response=self.client.post("/api/translate",json={"text":"Buongiorno, professore.","src":"it","to":"pt"})
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.json["text"],"Bom dia, professor.")
                self.assertIn("it%7Cpt",translated.call_args.args[0].full_url)

    def test_invalid_requests(self):
        self.assertEqual(self.client.post("/api/join",json={"name":"Anon","consent":False}).status_code,400)
        self.assertEqual(self.client.post("/api/join",json={"name":"Anon","room":"BAD","consent":True}).status_code,404)
        self.assertEqual(self.client.post("/api/translate",json={"text":"Olá","src":"pt","to":"pt"}).json["text"],"Olá")
        host=self.join("Host")
        self.assertEqual(self.client.post("/api/call-action",json={"room":host["room"],"pid":host["pid"],"target":"fake","action":"accepted","reply":"ok"}).status_code,404)

if __name__=="__main__": unittest.main()
