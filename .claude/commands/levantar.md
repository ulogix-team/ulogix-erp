---
description: Levanta el stack en Docker y verifica que el dashboard responde
---

Levanta el stack completo:

```bash
docker compose -f docker-compose.dashboard.yml up -d --build
```

El `--build` importa: el Dockerfile fija `OPENBLAS_NUM_THREADS=1` (y OMP/MKL/
NUMEXPR), que es lo que evita los segfaults `exit 139` de statsmodels en
WSL/Docker.

Luego:
1. `docker compose -f docker-compose.dashboard.yml ps` — ambos servicios
   (`dashboard`, `middleware`) deben estar `Up`.
2. `docker compose -f docker-compose.dashboard.yml logs --tail 40 dashboard` —
   busca la URL local y confirma que no hay tracebacks.
3. Reporta al usuario la URL (`http://localhost:8501`).

Si el dashboard reinicia en bucle (`exited with code 139`), confirma que las
variables de entorno de hilos están en el contenedor:
`docker compose -f docker-compose.dashboard.yml exec dashboard env | grep THREADS`
