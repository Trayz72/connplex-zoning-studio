import express from 'express';
import cors from 'cors';
import cookieParser from 'cookie-parser';
import authRoutes from './routes/auth.js';
import projectRoutes from './routes/projects.js';
import adminRoutes from './routes/admin.js';
import rulesConfigRoutes from './routes/rulesConfig.js';

const app = express();
const port = process.env.PORT || 3001;

// origin:true reflects whatever Origin header the request sent, which —
// combined with credentials:true — lets any site make credentialed
// requests here, not just this app's real frontend. Fine for local dev
// (no other origin can reach localhost anyway); set FRONTEND_ORIGIN to the
// deployed frontend's real origin (e.g. https://connplex-web.onrender.com,
// no trailing slash) once this is hosted somewhere reachable from outside.
const allowedOrigin = process.env.FRONTEND_ORIGIN || true;
app.use(cors({
  origin: allowedOrigin,
  credentials: true
}));

app.use(express.json());
app.use(cookieParser());

// Namespaced under /api/pm so these routes can never collide with a frontend
// route sharing the same prefix (e.g. /projects/:id/studio) — see api.ts.
app.use('/api/pm/auth', authRoutes);
app.use('/api/pm/projects', projectRoutes);
app.use('/api/pm/admin', adminRoutes);
app.use('/api/pm/admin/rules-config', rulesConfigRoutes);

app.listen(port, () => {
  console.log(`Project service listening on port ${port}`);
});

export default app;
