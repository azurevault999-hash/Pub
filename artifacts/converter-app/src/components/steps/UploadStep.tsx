import { useState, useCallback } from "react";
import { UploadCloud, FileType, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import type { UploadResponse } from "@workspace/api-client-react";
import { useToast } from "@/hooks/use-toast";

interface UploadStepProps {
  onUploadSuccess: (res: UploadResponse) => void;
}

export function UploadStep({ onUploadSuccess }: UploadStepProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { toast } = useToast();

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const onDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const uploadFile = async (file: File) => {
    if (!file.name.endsWith(".csv")) {
      setError("Only CSV files are allowed.");
      return;
    }
    if (file.size > 100 * 1024 * 1024) {
      setError("File size exceeds 100MB limit.");
      return;
    }

    setError(null);
    setIsUploading(true);

    try {
      const base = import.meta.env.BASE_URL.replace(/\/$/, "");
      const formData = new FormData();
      formData.append("file", file);
      
      const res = await fetch(`${base}/api/upload`, { 
        method: "POST", 
        body: formData 
      });
      
      const data = await res.json();
      
      if (!res.ok) {
        throw new Error(data.error || "Upload failed");
      }

      toast({
        title: "Upload successful",
        description: `Successfully uploaded ${file.name}`,
      });
      
      onUploadSuccess(data);
    } catch (err: any) {
      setError(err.message || "An unexpected error occurred during upload.");
    } finally {
      setIsUploading(false);
    }
  };

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      uploadFile(e.dataTransfer.files[0]);
    }
  }, []);

  const onFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      uploadFile(e.target.files[0]);
    }
  };

  return (
    <div className="flex-1 flex flex-col items-center justify-center max-w-2xl mx-auto w-full animate-in fade-in zoom-in duration-300">
      <div className="text-center mb-8">
        <h2 className="text-3xl font-bold tracking-tight mb-2 text-foreground">Upload Source Data</h2>
        <p className="text-muted-foreground">Select or drag & drop your Shopify products CSV export to begin the migration process.</p>
      </div>

      {error && (
        <Alert variant="destructive" className="mb-6 w-full">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Upload Error</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Card className="w-full">
        <CardContent className="p-0">
          <label
            htmlFor="file-upload"
            className={`flex flex-col items-center justify-center w-full h-80 border-2 border-dashed rounded-lg cursor-pointer transition-colors ${
              isDragging ? "border-primary bg-primary/5" : "border-border hover:border-primary/50 hover:bg-muted/50"
            } ${isUploading ? "opacity-50 pointer-events-none" : ""}`}
            onDragOver={onDragOver}
            onDragLeave={onDragLeave}
            onDrop={onDrop}
          >
            <div className="flex flex-col items-center justify-center pt-5 pb-6">
              {isUploading ? (
                <div className="flex flex-col items-center">
                  <div className="w-12 h-12 rounded-full border-4 border-primary border-t-transparent animate-spin mb-4" />
                  <p className="mb-2 text-sm text-foreground font-medium">Uploading and processing file...</p>
                  <p className="text-xs text-muted-foreground">This may take a few moments for large datasets</p>
                </div>
              ) : (
                <>
                  <div className="w-16 h-16 mb-4 rounded-full bg-muted flex items-center justify-center">
                    <UploadCloud className="w-8 h-8 text-muted-foreground" />
                  </div>
                  <p className="mb-2 text-sm text-foreground font-medium">
                    <span className="text-primary">Click to select</span> or drag and drop
                  </p>
                  <p className="text-xs text-muted-foreground mb-4">Shopify CSV (Max 100MB)</p>
                  <Button variant="secondary" size="sm" className="pointer-events-none">
                    Select File
                  </Button>
                </>
              )}
            </div>
            <input 
              id="file-upload" 
              type="file" 
              accept=".csv" 
              className="hidden" 
              onChange={onFileInput}
              disabled={isUploading}
            />
          </label>
        </CardContent>
      </Card>
      
      <div className="mt-8 grid grid-cols-1 md:grid-cols-3 gap-4 w-full">
        <div className="p-4 rounded-lg bg-card border border-border flex gap-3">
          <FileType className="w-5 h-5 text-primary shrink-0" />
          <div className="text-sm">
            <p className="font-medium">Valid Format</p>
            <p className="text-muted-foreground text-xs mt-1">Standard Shopify export</p>
          </div>
        </div>
        <div className="p-4 rounded-lg bg-card border border-border flex gap-3">
          <FileType className="w-5 h-5 text-primary shrink-0" />
          <div className="text-sm">
            <p className="font-medium">Data Privacy</p>
            <p className="text-muted-foreground text-xs mt-1">Processed locally on server</p>
          </div>
        </div>
        <div className="p-4 rounded-lg bg-card border border-border flex gap-3">
          <FileType className="w-5 h-5 text-primary shrink-0" />
          <div className="text-sm">
            <p className="font-medium">Size Limit</p>
            <p className="text-muted-foreground text-xs mt-1">Up to 100MB per file</p>
          </div>
        </div>
      </div>
    </div>
  );
}
