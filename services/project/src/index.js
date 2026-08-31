import express from 'express';
import cors from 'cors';
import cookieParser from 'cookie-parser';
import authRoutes from './routes/auth.js';
import projectRoutes from './routes/projects.js';

const app = express();
const port = process.env.PORT || 3001;

app.use(cors({
  origin: true,
  credentials: true
}));

app.use(express.json());
app.use(cookieParser());

// Namespaced under /api/pm so these routes can never collide with a frontend
// route sharing the same prefix (e.g. /projects/:id/studio) — see api.ts.
app.use('/api/pm/auth', authRoutes);
app.use('/api/pm/projects', projectRoutes);

app.listen(port, () => {
  console.log(`Project service listening on port ${port}`);
});

export default app;
