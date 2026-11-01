// UI strings only (never answers). Language packs beyond these three are Phase 2.
export type Lang = "en" | "ur" | "ur-Latn";

const en = {
  launcher: "Ask us anything",
  open: "Open chat assistant",
  close: "Close chat",
  title: "Assistant",
  subtitle: "Answers only from {org}'s published information",
  placeholder: "Type your question…",
  send: "Send",
  searching: "Searching sources…",
  reranking: "Checking which sources are relevant…",
  writing: "Writing a cited answer…",
  sources: "Sources",
  confidence: { high: "High evidence", medium: "Medium evidence", low: "Limited evidence" },
  confidenceHelp:
    "Shows how well the answer is supported by the available sources — not a guarantee that it is correct.",
  handoffTitle: "Talk to a person",
  whatsapp: "Chat on WhatsApp",
  email: "Send us a message",
  booking: "Book a call",
  name: "Name (optional)",
  emailField: "Your email",
  message: "How can we help? (optional)",
  consent: "I agree to be contacted about my question.",
  submit: "Send message",
  submitting: "Sending…",
  sent: "Thanks — your message was received. The team will reply by email.",
  noChannels: "Contact options haven't been set up yet.",
  helpful: "Helpful",
  notHelpful: "Not helpful",
  thanks: "Thanks for the feedback.",
  error: "Something went wrong. Please try again.",
  retry: "Try again",
  unavailable: "The assistant is unavailable right now.",
  poweredBy: "Answers include sources. Verify important details with the team.",
};

type Strings = typeof en;

const ur: Strings = {
  ...en,
  launcher: "ہم سے کچھ بھی پوچھیں",
  open: "چیٹ اسسٹنٹ کھولیں",
  close: "چیٹ بند کریں",
  title: "اسسٹنٹ",
  subtitle: "صرف {org} کی شائع شدہ معلومات سے جوابات",
  placeholder: "اپنا سوال لکھیں…",
  send: "بھیجیں",
  searching: "ذرائع تلاش کیے جا رہے ہیں…",
  reranking: "متعلقہ ذرائع جانچے جا رہے ہیں…",
  writing: "حوالوں کے ساتھ جواب لکھا جا رہا ہے…",
  sources: "ذرائع",
  confidence: { high: "مضبوط ثبوت", medium: "درمیانہ ثبوت", low: "محدود ثبوت" },
  confidenceHelp: "یہ دکھاتا ہے کہ جواب دستیاب ذرائع سے کتنا ثابت ہے — یہ درستگی کی ضمانت نہیں۔",
  handoffTitle: "کسی فرد سے بات کریں",
  whatsapp: "واٹس ایپ پر بات کریں",
  email: "ہمیں پیغام بھیجیں",
  booking: "کال بک کریں",
  error: "کچھ غلط ہو گیا۔ دوبارہ کوشش کریں۔",
  retry: "دوبارہ کوشش کریں",
};

const urLatn: Strings = {
  ...en,
  launcher: "Hum se kuch bhi poochein",
  subtitle: "Sirf {org} ki published maloomat se jawab",
  placeholder: "Apna sawal likhein…",
  searching: "Sources talash ho rahe hain…",
  handoffTitle: "Kisi insaan se baat karein",
};

const TABLE: Record<Lang, Strings> = { en, ur, "ur-Latn": urLatn };

export function strings(lang: string | null | undefined): Strings {
  return TABLE[(lang as Lang) in TABLE ? (lang as Lang) : "en"];
}

export function isRtl(lang: string | null | undefined): boolean {
  return lang === "ur";
}
