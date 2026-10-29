# Cadastro editorial verificável — Livro sem Fronteiras

Cada obra é identificada por um título e por uma URL pública válida. As informações enriquecidas são cadastradas em `catalogo_adicional.json`.

## Exemplo de registro

```json
[
  {
    "id": "identificador-constante-da-obra",
    "title": "Título exato da publicação",
    "url": "https://exemplo.org/pagina-oficial",
    "source": "Editora ou acervo de origem",
    "source_url": "https://exemplo.org/pagina-com-dados-bibliograficos",
    "kind": "publicação",
    "author": "Nome da pessoa autora",
    "language": "pt",
    "edition": "1ª edição, 2026",
    "summary": "Resumo elaborado com base na obra consultada.",
    "summary_verified": false,
    "cover_url": "",
    "cover_verified": false,
    "verified_at": ""
  }
]
```

**Importante:** o exemplo acima é um esquema ilustrativo, não um registro real. Para publicar um resumo como verificado, consulte o conteúdo da obra e registre `summary_verified: true`. Para publicar uma capa como oficial, confirme que corresponde à edição indicada e que existe autorização para exibi-la, e então use `cover_verified: true`. Não atribua dados, fotos ou idiomas por suposição.

Se uma obra já constar no catálogo de origem com o mesmo `id` ou `url`, os metadados editoriais podem enriquecê-la sem criar um novo registro. Há um endpoint de auditoria em `/api/catalog-audit` para acompanhar quantas capas e sinopses verificadas foram cadastradas.

O serviço gratuito do Render não mantém alterações locais após novas implantações: atualize o arquivo JSON no GitHub para preservar o catálogo.
