# LIVRO SEM FRONTEIRAS — pacote Render

## Publicação
1. Extraia o ZIP, e envie TODOS os arquivos da pasta `livro_sem_fronteiras_render` à raiz de um novo repositório GitHub (não inclua uma pasta extra acima deles).
2. No Render: New > Blueprint > conecte esse repositório e use `render.yaml`. Como alternativa, New > Web Service, runtime Python, comando Build `pip install -r requirements.txt`, comando Start `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 60`.
3. Aguarde o deploy do serviço e abra seu endereço `https://...onrender.com/`.
4. Teste `/api/health` (status `ok`) e `/api/catalog` (count e registros; se a fonte externa falhar, campo `warning`).
5. Confirme links individuais e permissões do Drive. A política jurídica requer confirmação de atendimento/operador de dados antes da divulgação comercial.

## Como funciona o total de obras
- `/api/catalog` consulta periodicamente o catálogo público original e extrai os links de arquivo Google Drive.
- O total dinâmico representa links de registros únicos, não necessariamente livros autorais únicos.
- O campo `source_count` mostra a quantidade extraída do portal original; `additional_count` mostra inclusões não repetidas.
- Se o servidor do site de origem bloquear a consulta automática, o sistema informa a falha e conserva os registros da última consulta válida na memória do processo. Em caso de reinício, a cache é refeita.
- Para adicionar obras publicadas confirmadas, edite `catalogo_adicional.json` usando itens `{"title":"Título", "url":"https://...", "source":"Fonte", "kind":"publicação"}`. Não insira livros sem link verificado.

## Cuidados importantes
- A lista de 15 músicas contém gravações INSTRUMENTAIS ORIGINAIS do pacote anterior, não gravações de rituais ou composições históricas de Mozart.
- A tradução da interface usa integração externa do navegador e depende de disponibilidade; não afirma traduzir arquivos privados automaticamente.
- Não coloque credenciais no repositório. Nenhuma chave secreta é necessária.
- O pacote foi testado localmente pelo cliente de testes Flask, não equivale a uma publicação concluída no Render.
