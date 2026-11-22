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

    def test_invalid_requests(self):
        self.assertEqual(self.client.post("/api/join",json={"name":"Anon","consent":False}).status_code,400)
        self.assertEqual(self.client.post("/api/join",json={"name":"Anon","room":"BAD","consent":True}).status_code,404)
        self.assertEqual(self.client.post("/api/translate",json={"text":"Olá","src":"pt","to":"pt"}).json["text"],"Olá")
        host=self.join("Host")
        self.assertEqual(self.client.post("/api/call-action",json={"room":host["room"],"pid":host["pid"],"target":"fake","action":"accepted","reply":"ok"}).status_code,404)

if __name__=="__main__": unittest.main()
