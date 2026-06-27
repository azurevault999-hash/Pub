import { useState } from "react";
import { Switch, Route, Router as WouterRouter } from "wouter";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ThemeProvider } from "@/components/ThemeProvider";
import NotFound from "@/pages/not-found";
import { UploadStep } from "@/components/steps/UploadStep";
import { AnalysisStep } from "@/components/steps/AnalysisStep";
import { ValidationStep } from "@/components/steps/ValidationStep";
import { ConversionStep } from "@/components/steps/ConversionStep";
import { DownloadStep } from "@/components/steps/DownloadStep";
import { Moon, Sun, ArrowRight, CheckCircle2 } from "lucide-react";
import { useTheme } from "next-themes";
import { Button } from "@/components/ui/button";

import type { UploadResponse } from "@workspace/api-client-react";

const queryClient = new QueryClient();

const STEPS = [
  { id: 0, title: "Upload" },
  { id: 1, title: "Analysis" },
  { id: 2, title: "Validation" },
  { id: 3, title: "Conversion" },
  { id: 4, title: "Download" },
];

function Wizard() {
  const [currentStep, setCurrentStep] = useState(0);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [uploadResult, setUploadResult] = useState<UploadResponse | null>(null);
  const { theme, setTheme } = useTheme();

  const handleUploadSuccess = (res: UploadResponse) => {
    setSessionId(res.session_id);
    setUploadResult(res);
    setCurrentStep(1);
  };

  return (
    <div className="min-h-screen bg-background text-foreground font-sans flex flex-col">
      <header className="border-b border-border/40 bg-card/50 backdrop-blur sticky top-0 z-50">
        <div className="container max-w-6xl mx-auto px-4 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded bg-primary/20 flex items-center justify-center border border-primary/50">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-primary"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/></svg>
            </div>
            <h1 className="font-bold text-lg tracking-tight">Shopify <span className="text-muted-foreground font-normal mx-1">→</span> WooCommerce</h1>
          </div>
          
          <div className="flex items-center gap-6">
            <nav className="hidden md:flex items-center gap-2">
              {STEPS.map((step, idx) => (
                <div key={step.id} className="flex items-center">
                  <button
                    onClick={() => setCurrentStep(step.id)}
                    disabled={idx > currentStep && !(sessionId)}
                    className={`flex items-center justify-center w-8 h-8 rounded-full text-sm font-medium transition-colors ${
                      currentStep === step.id
                        ? "bg-primary text-primary-foreground"
                        : currentStep > step.id || (sessionId && idx <= currentStep)
                        ? "bg-muted text-foreground hover:bg-muted/80 cursor-pointer"
                        : "bg-transparent border border-border text-muted-foreground opacity-50 cursor-not-allowed"
                    }`}
                  >
                    {currentStep > step.id ? <CheckCircle2 className="w-4 h-4" /> : step.id + 1}
                  </button>
                  {idx < STEPS.length - 1 && (
                    <div className={`w-8 h-px mx-2 ${currentStep > step.id ? "bg-primary/50" : "bg-border"}`} />
                  )}
                </div>
              ))}
            </nav>
            
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setTheme(theme === "light" ? "dark" : "light")}
              className="w-9 h-9"
            >
              <Sun className="h-4 w-4 rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0" />
              <Moon className="absolute h-4 w-4 rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100" />
              <span className="sr-only">Toggle theme</span>
            </Button>
          </div>
        </div>
      </header>

      <main className="flex-1 container max-w-5xl mx-auto px-4 py-8 flex flex-col">
        {currentStep === 0 && <UploadStep onUploadSuccess={handleUploadSuccess} />}
        {currentStep === 1 && sessionId && uploadResult && (
          <AnalysisStep 
            sessionId={sessionId} 
            initialData={uploadResult.analysis} 
            onNext={() => setCurrentStep(2)} 
          />
        )}
        {currentStep === 2 && sessionId && (
          <ValidationStep 
            sessionId={sessionId} 
            onNext={() => setCurrentStep(3)} 
            onBack={() => setCurrentStep(1)} 
          />
        )}
        {currentStep === 3 && sessionId && (
          <ConversionStep 
            sessionId={sessionId} 
            onNext={() => setCurrentStep(4)} 
            onBack={() => setCurrentStep(2)} 
          />
        )}
        {currentStep === 4 && sessionId && (
          <DownloadStep 
            sessionId={sessionId} 
            onReset={() => {
              setSessionId(null);
              setUploadResult(null);
              setCurrentStep(0);
            }} 
          />
        )}
      </main>
    </div>
  );
}

function Router() {
  return (
    <Switch>
      <Route path="/" component={Wizard} />
      <Route component={NotFound} />
    </Switch>
  );
}

function App() {
  return (
    <ThemeProvider attribute="class" defaultTheme="dark" enableSystem={false}>
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          <WouterRouter base={import.meta.env.BASE_URL.replace(/\/$/, "")}>
            <Router />
          </WouterRouter>
          <Toaster />
        </TooltipProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}

export default App;
