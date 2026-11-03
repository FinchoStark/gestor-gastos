# Despliegue paso a paso

Orden recomendado: **GitHub → Vercel → Neon (PostgreSQL) → clave de Claude → AWS S3**.
La app funciona desde el paso 2 (en modo demo), pero sin las variables de acceso responde 503: es a propósito, para que nunca quede abierta en internet.

## 1. Subir el código a GitHub

```bash
git add .
git commit -m "Gestor de gastos: primera versión"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/gestor-gastos.git
git push -u origin main
```

## 2. Vercel

1. Entra en https://vercel.com con tu cuenta de GitHub.
2. **Add New → Project** e importa `gestor-gastos`.
3. Vercel detecta FastAPI solo (busca `app` en `app/main.py`).
4. Antes de pulsar **Deploy**, en **Environment Variables** añade el acceso a la app:

| Variable | Valor |
|---|---|
| `APP_USUARIO` | el usuario que quieras |
| `APP_CONTRASENA` | una contraseña larga y aleatoria |

5. Pulsa **Deploy**. El navegador pedirá ese usuario y contraseña al abrir la web.

En `vercel.json` se sube el tiempo máximo de la función a 60 s, porque leer varias fotos con la IA puede tardar, y se fija la región en Frankfurt (`fra1`), cerca de la base de datos y dentro de Europa. Si tu base de datos está en otra región, cámbiala ahí.

## 3. PostgreSQL con Neon

1. En el proyecto de Vercel: **Storage → Create Database → Neon** (plan gratuito).
2. Conéctala al proyecto: Vercel añade la variable `DATABASE_URL` automáticamente.
3. **Redeploy**. Las tablas se crean solas en el primer arranque.

Para usar la misma base de datos en local, copia esa `DATABASE_URL` en tu `.env`.

Si ya tienes una base de datos en Neon, no crees otra: añade su cadena de conexión como variable `DATABASE_URL` en **Settings → Environment Variables** y haz **Redeploy**.

## 4. Clave de la API de Claude

1. https://console.anthropic.com → **API Keys → Create Key** (hace falta añadir algo de saldo; cada ticket cuesta céntimos).
2. En Vercel: **Settings → Environment Variables** → `ANTHROPIC_API_KEY`.
3. Redeploy. En la cabecera de la web verás "IA: Claude ✓".

## 5. AWS S3 para las fotos

### Si es tu primera vez en AWS

1. **Crea la cuenta** en https://aws.amazon.com. Si te ofrece dos formas de alta, elige la avanzada, con usuario *root*: en la otra no se puede activar la región de España.
2. **Elige el plan.** La cuenta del plan gratuito se cierra sola a los 6 meses o al agotar los créditos, así que para guardar fotos de verdad usa el de pago, que también puede incluir créditos.
3. **Protege el usuario root** con MFA: nombre de la cuenta (arriba a la derecha) → **Security credentials → Assign MFA device → Authenticator app**. Guarda una copia del código secreto. No uses el root para el día a día ni le crees claves de acceso.
4. **Pon una alerta de gasto**: **Billing and Cost Management → Budgets**, con un presupuesto mensual pequeño y tu email. Avisa, pero no corta el servicio.
5. **Activa la región de España**, que viene desactivada: nombre de la cuenta → **Account → AWS Regions → Europe (Spain) → Enable**. Es gratis; suele tardar unos minutos, pero puede tardar horas. Espera a que esté activa antes de seguir.

### Bucket y permisos

En la consola de AWS:

1. **S3 → Create bucket** (con la región **Europe (Spain)** seleccionada)
   - Nombre: por ejemplo `gestor-gastos-tickets-tunombre` (tiene que ser único en todo AWS)
   - Región: `eu-south-2` (España)
   - Deja marcado **Block all public access**: las fotos se ven con URLs firmadas temporales.
2. **IAM → Users → Create user** (por ejemplo `gestor-gastos-app`), sin acceso a la consola.
3. Añádele una política *inline* con permiso solo sobre ese bucket (mínimo privilegio):

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["s3:PutObject", "s3:GetObject"],
    "Resource": "arn:aws:s3:::NOMBRE-DE-TU-BUCKET/*"
  }]
}
```

4. En el usuario: **Security credentials → Create access key** (tipo "Application running outside AWS").
5. En Vercel añade:

| Variable | Valor |
|---|---|
| `S3_BUCKET` | nombre del bucket |
| `S3_REGION` | `eu-south-2` |
| `S3_ACCESS_KEY_ID` | la access key |
| `S3_SECRET_ACCESS_KEY` | la secret key |

> Vercel reserva los nombres `AWS_*`, por eso la app usa `S3_*`.

6. Redeploy. En la cabecera: "Fotos: AWS S3 ✓".

## Comprobación final

- `https://TU-PROYECTO.vercel.app/api/salud` debe pedir usuario y contraseña, y después devolver `base_datos: true`, `ia: "claude"`, `almacenamiento: "s3"`.
- Abre la web desde el móvil, haz una foto a un ticket real y revisa el resultado.
- Si algo falla: Vercel → proyecto → **Logs**.
