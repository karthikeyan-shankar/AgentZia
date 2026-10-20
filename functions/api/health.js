import { json, MODEL_DEFAULT } from "../../lib/zia.js";

export const onRequestGet = ({ env }) =>
  json({ ai: !!env.GROQ_API_KEY, model: env.GROQ_MODEL || MODEL_DEFAULT, locked: !!env.ZIA_PASSCODE, storage: !!env.DB });
