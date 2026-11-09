# Active projects

Projects are active by default. The shared flag controls page visibility only;
execution, queue order, limits and notices are unaffected. `NEW` is always active.

```sh
cplane project list
cplane project active FAC
cplane project active FAC off --actor owner
cplane project active FAC on --actor owner
```

Activation also creates the project's orchestrator chat if missing, using the
project chat defaults. Repeated activation reuses the existing chat. Deactivation
keeps all features, chats and documents. Settings › Projects changes the same flag.

Project pages and owner field editing use the same store methods as the CLI:

```sh
cplane project add SYN 'Synthetic project' --actor owner
cplane project set SYN --name 'Synthetic' --about 'What we are building.' \
  --public-url https://example.test --repository-url https://example.test/repo \
  --actor owner
```

Keys are permanent and unique; adding creates an active project with its chat.
Names allow 1–60 characters and About allows up to 600. URLs must use HTTPS;
pass an empty URL to remove it. See [Project pages](project-pages.md) for usage
accounting, validation and installation.
