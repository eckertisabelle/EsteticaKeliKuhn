# Estética Keli Kuhn — publicação no GitHub + Render + Neon

## 1. Criar o banco novo no Neon
1. Entre em https://neon.tech e crie um projeto PostgreSQL novo.
2. Abra **SQL Editor** no projeto.
3. Abra o arquivo `schema.sql` deste pacote, copie todo o conteúdo e execute.
4. Em **Connect**, copie a connection string PostgreSQL (use a opção pooled ou direct; mantenha `sslmode=require`).
5. Guarde a URL em local seguro. Não a publique no GitHub.

O banco começa vazio. Cadastros, clientes, produtos, serviços e agendamentos do banco antigo não são copiados automaticamente.

## 2. Publicar no GitHub
1. Extraia este ZIP.
2. Crie um repositório novo no GitHub.
3. Envie os arquivos da pasta para a raiz do repositório: `app.py`, `index.html`, `requirements.txt`, `render.yaml`, `schema.sql`, `.gitignore` e `.env.example`.
4. Não envie `.env` nem a URL do banco.

## 3. Criar o serviço no Render
1. Entre em https://render.com e escolha **New + → Blueprint**.
2. Conecte o repositório GitHub criado.
3. O Render encontrará `render.yaml` e criará o serviço web.
4. No serviço, abra **Environment** e preencha:
   - `DATABASE_URL`: URL do banco Neon novo, completa.
   - `KELI_PASSWORD`: senha forte para a conta Keli.
   - `AMANDA_PASSWORD`: senha forte para a conta Amanda.
   - `KELI_CPF`: CPF da Keli com 11 números, somente dígitos.
5. Salve e aguarde o deploy terminar. Acesse a URL `.onrender.com`.

`FLASK_SECRET_KEY` é gerada pelo Blueprint. `SESSION_COOKIE_SECURE=1` já está configurada para HTTPS no Render.

## 4. Observações importantes
- A aplicação utiliza PostgreSQL/Neon e as tabelas do `schema.sql`.
- O site é servido pelo próprio Flask, portanto o HTML deve permanecer junto do `app.py` com o nome `index.html`.
- Não coloque senhas, CPF ou `DATABASE_URL` em arquivos versionados.
- O banco novo fica vazio; se quiser manter os dados atuais, será necessário exportar e importar os dados do banco antigo separadamente.
- O plano gratuito do Render pode suspender o serviço após inatividade; a primeira abertura pode demorar.
