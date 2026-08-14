import { createClient } from "@supabase/supabase-js";

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

if (!supabaseUrl || !supabaseAnonKey) {
  // Fails loudly at import time rather than surfacing as a confusing blank
  // page or a cryptic fetch error the first time a query runs.
  throw new Error(
    "Missing VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY -- copy .env.example to .env.local and fill them in."
  );
}

export const supabase = createClient(supabaseUrl, supabaseAnonKey);
