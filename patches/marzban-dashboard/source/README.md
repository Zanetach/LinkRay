# LinkRay Dashboard Source Patch

This directory contains the source-level dashboard patch for Marzban.

The runtime deployment still ships the compiled compatibility snapshot in
`patches/marzban-dashboard/current/`, because production hosts run the Marzban
Docker image and do not build the dashboard from source.

Use this source patch when upgrading Marzban:

```bash
git clone https://github.com/Gozargah/Marzban.git
cd Marzban
git checkout master
git apply /path/to/linkray/patches/marzban-dashboard/source/linkray-dashboard.patch
cd app/dashboard
npm ci
npm run build
```

Then replace the compatibility snapshot only after verifying the generated
dashboard behaves the same:

- user link button opens all LinkRay subscription formats
- subscription list starts with automatic detection
- Node Info panel uses `/api/linkray/nodes`
- Node Info refresh button calls `/api/linkray/nodes/refresh`
- Node Info pagination shows 10 rows per page

