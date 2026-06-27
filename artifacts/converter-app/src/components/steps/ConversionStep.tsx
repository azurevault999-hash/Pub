import { useState, useEffect, useRef } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  ArrowRight, ArrowLeft, Play, Package, Layers, Image, Tag, FolderOpen,
  AlertTriangle, XCircle, Clock, CheckCircle2, Terminal,
} from "lucide-react";
import {
  useRunConversion,
  useGetConversion,
  getGetConversionQueryKey,
} from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";

interface ConversionStepProps {
  sessionId: string;
  onNext: () => void;
  onBack: () => void;
}

function StatRow({ icon: Icon, label, value, highlight = false }: {
  icon: React.ElementType;
  label: string;
  value: number | string;
  highlight?: boolean;
}) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-border last:border-0">
      <div className="flex items-center gap-2 text-sm">
        <Icon className={`w-4 h-4 ${highlight ? "text-primary" : "text-muted-foreground"}`} />
        <span className={highlight ? "text-foreground font-medium" : "text-muted-foreground"}>{label}</span>
      </div>
      <span className={`font-mono text-sm ${highlight ? "text-foreground font-semibold" : "text-muted-foreground"}`}>
        {value}
      </span>
    </div>
  );
}

export function ConversionStep({ sessionId, onNext, onBack }: ConversionStepProps) {
  const [progress, setProgress] = useState(0);
  const [started, setStarted] = useState(false);
  const progressRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();

  const runConversion = useRunConversion();
  const { data: conversionData } = useGetConversion(
    sessionId,
    { query: { enabled: !!sessionId, queryKey: getGetConversionQueryKey(sessionId) } }
  );

  const isRunning = runConversion.isPending;
  const isDone = !!conversionData;
  const hasError = !!runConversion.error;

  // Fake progress animation while converting
  useEffect(() => {
    if (isRunning) {
      setProgress(5);
      progressRef.current = setInterval(() => {
        setProgress((p) => {
          if (p >= 92) return p;
          return p + Math.random() * 4;
        });
      }, 400);
    } else {
      if (progressRef.current) clearInterval(progressRef.current);
      if (isDone) setProgress(100);
    }
    return () => {
      if (progressRef.current) clearInterval(progressRef.current);
    };
  }, [isRunning, isDone]);

  // Auto-scroll log
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [conversionData?.log_lines]);

  const handleConvert = () => {
    setStarted(true);
    setProgress(0);
    runConversion.mutate(
      { sessionId },
      {
        onSuccess: () => {
          queryClient.invalidateQueries({ queryKey: getGetConversionQueryKey(sessionId) });
        },
      }
    );
  };

  return (
    <div className="w-full space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-300">
      <div>
        <h2 className="text-2xl font-bold tracking-tight mb-1">Conversion</h2>
        <p className="text-muted-foreground text-sm">
          Convert your Shopify data to a WooCommerce 10.9.1 compatible CSV with full support for
          simple and variable products, attributes, images, and SEO metadata.
        </p>
      </div>

      {/* Start button / idle */}
      {!started && !isDone && (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center py-16">
            <div className="w-16 h-16 rounded-full bg-primary/10 border border-primary/30 flex items-center justify-center mb-4">
              <Play className="w-7 h-7 text-primary ml-0.5" />
            </div>
            <p className="font-semibold text-lg mb-1">Ready to convert</p>
            <p className="text-muted-foreground text-sm text-center max-w-sm mb-6">
              Click below to run the conversion engine and generate WooCommerce-compatible output files.
            </p>
            <Button onClick={handleConvert} size="lg" data-testid="button-run-conversion">
              <Play className="w-4 h-4 mr-2" />
              Generate WooCommerce CSV
            </Button>
          </CardContent>
        </Card>
      )}

      {/* In-progress */}
      {isRunning && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-primary animate-pulse" />
              Converting…
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <Progress value={progress} className="h-2" />
            <div className="space-y-2">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-5 w-full" />
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Error */}
      {hasError && !isRunning && (
        <Alert variant="destructive">
          <XCircle className="h-4 w-4" />
          <AlertDescription>
            Conversion failed. Please check your source file and try again.
          </AlertDescription>
        </Alert>
      )}

      {/* Results */}
      {isDone && !isRunning && conversionData && (
        <>
          <Alert className="border-green-500/30 bg-green-500/5 text-green-600 dark:text-green-400">
            <CheckCircle2 className="h-4 w-4" />
            <AlertDescription>
              Conversion complete — {conversionData.products_converted} product(s) converted in{" "}
              {conversionData.execution_time_seconds.toFixed(2)}s.
            </AlertDescription>
          </Alert>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Stats */}
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
                  Results
                </CardTitle>
              </CardHeader>
              <CardContent>
                <StatRow icon={Package} label="Products converted" value={conversionData.products_converted} highlight />
                <StatRow icon={Package} label="Products failed" value={conversionData.products_failed} />
                <StatRow icon={Layers} label="Variants converted" value={conversionData.variants_converted} />
                <StatRow icon={FolderOpen} label="Categories mapped" value={conversionData.categories_mapped} />
                <StatRow icon={Tag} label="Tags preserved" value={conversionData.tags_preserved} />
                <StatRow icon={Image} label="Images mapped" value={conversionData.images_mapped} />
                <StatRow icon={AlertTriangle} label="Warnings" value={conversionData.warnings} />
                <StatRow icon={XCircle} label="Errors" value={conversionData.errors} />
                <StatRow icon={Clock} label="Execution time" value={`${conversionData.execution_time_seconds.toFixed(3)}s`} />
              </CardContent>
            </Card>

            {/* Output files */}
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
                  Output Files
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {conversionData.output_files.map((file) => (
                    <div key={file} className="flex items-center gap-2 text-sm py-1.5 border-b border-border last:border-0">
                      <CheckCircle2 className="w-4 h-4 text-green-500 shrink-0" />
                      <span className="font-mono text-xs">{file}</span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Log */}
          {conversionData.log_lines.length > 0 && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-2">
                  <Terminal className="w-4 h-4" />
                  Conversion Log
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div
                  ref={logRef}
                  className="bg-black/50 rounded-md p-4 h-56 overflow-y-auto font-mono text-xs text-green-400/90 space-y-0.5"
                  data-testid="text-conversion-log"
                >
                  {conversionData.log_lines.map((line, i) => (
                    <div key={i} className="leading-relaxed">{line}</div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </>
      )}

      <div className="flex items-center justify-between pt-2">
        <Button variant="ghost" onClick={onBack} size="sm" disabled={isRunning} data-testid="button-back-validation">
          <ArrowLeft className="w-4 h-4 mr-2" />
          Back
        </Button>
        <Button
          onClick={onNext}
          disabled={!isDone || isRunning}
          size="lg"
          data-testid="button-next-downloads"
        >
          View Downloads
          <ArrowRight className="w-4 h-4 ml-2" />
        </Button>
      </div>
    </div>
  );
}
