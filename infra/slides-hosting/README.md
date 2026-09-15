# Hosting de la presentación

Stack independiente del lab con S3 privado, certificado ACM en `us-east-1`, CloudFront con OAC y la web ACL requerida por el plan Free. Usa una key de state exclusiva y gestiona su cierre por separado.

## Preparación

Copiar los ejemplos de configuración a `.local/` y completar cuenta, perfil, dominio y bucket. Configurar `AWS_CONFIG_FILE` si los perfiles están fuera de la ubicación habitual.

```bash
terraform -chdir=infra/slides-hosting init \
  -backend-config=../../.local/slides-hosting.tfbackend
terraform -chdir=infra/slides-hosting plan \
  -var-file=../../.local/slides-hosting.tfvars \
  -out=../../.local/slides-hosting.tfplan
```

Revisar el plan guardado antes de aplicarlo. Los valores iniciales `create_distribution = false` y `serve_content = false` crean únicamente el certificado y el bucket protegido.

```bash
terraform -chdir=infra/slides-hosting apply \
  ../../.local/slides-hosting.tfplan
terraform -chdir=infra/slides-hosting output certificate_dns_records
```

## DNS y activación

1. Agregar el CNAME de validación en el proveedor DNS, sin eliminar otros registros; conservarlo para la renovación del certificado.
2. Cuando ACM muestre `ISSUED`, cambiar `create_distribution` a `true`, generar un nuevo plan, revisarlo y aplicarlo.
3. La distribución se crea deshabilitada; contratar y verificar el plan **Free** en CloudFront antes de cambiar `serve_content` a `true`.
4. Generar, revisar y aplicar otro plan para habilitar la distribución; agregar el CNAME de `site_dns_record` en el proveedor DNS.
5. Publicar el build y verificar HTTPS, navegación y assets desde el dominio.

La suscripción de precios no está gestionada por este stack; se verifica por separado en AWS. No asumir que crear una distribución con Terraform activa el plan Free. La CLI debe soportar PricingPlanManager para gestionarlo por API; si no, usar la consola. No seleccionar un plan de pago sin aprobación.

También se puede usar un SDK actualizado con `pricing-plan-manager`. `CreateSubscription` requiere `planFamily="CloudFront"`, `planTier="FREE"`, `approvalMode="IMMEDIATE"` y los outputs `distribution_arn` y `web_acl_arn` en `resourceArns`. Verificar que la suscripción esté `ACTIVE` antes de habilitar la entrega. Mientras la suscripción no esté activa, WAF se factura por uso; completar la asociación sin dejar esta etapa pendiente innecesariamente. La ACL base no añade reglas de filtrado propias.

## Deploy

Publicar únicamente `slides/dist/`, nunca la raíz del repo. Las notas del presentador incluidas en el build también son públicas.

```bash
npm --prefix slides run build
terraform -chdir=infra/slides-hosting output -raw bucket_name
terraform -chdir=infra/slides-hosting output -raw distribution_id
```

Usar los outputs anteriores en estos comandos, con el perfil de la cuenta del hosting.

```bash
aws s3 sync slides/dist/ s3://BUCKET_DE_SLIDES/ \
  --profile PERFIL_DEL_HOSTING --cache-control 'public,max-age=300'
aws cloudfront create-invalidation --distribution-id DISTRIBUTION_ID \
  --paths '/*' --profile PERFIL_DEL_HOSTING
```

El sync no elimina objetos remotos; revisar archivos obsoletos antes de cualquier limpieza. El bucket no permite `force_destroy`, para evitar borrar contenido al desmontar por accidente.
