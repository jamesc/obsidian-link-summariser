# Azure OpenAI Integration

This document provides comprehensive guidance for using Obsidian Link Summarizer with Azure OpenAI / Microsoft Foundry.

## Overview

Azure OpenAI provides enterprise-grade access to OpenAI models (GPT-4, GPT-3.5-turbo, etc.) through Microsoft's infrastructure. This integration offers:

- **Enterprise Features**: SLA guarantees, data residency, enterprise security
- **Regional Availability**: Deploy in your preferred Azure region
- **Custom Rate Limits**: Configure limits based on your subscription tier
- **Cost Control**: Predictable pricing with Azure billing
- **Compliance**: GDPR, HIPAA, SOC 2 compliance built-in

## Prerequisites

### Azure Setup

1. **Azure Subscription**: Active Azure subscription
2. **Azure OpenAI Resource**: Create an Azure OpenAI resource in [Azure Portal](https://portal.azure.com)
3. **Model Deployment**: Deploy a model (e.g., GPT-4, GPT-3.5-turbo) in your resource
4. **API Keys**: Get your API keys from the resource's "Keys and Endpoint" section

### Important Azure Concepts

**Resource vs Deployment:**
- **Resource**: Your Azure OpenAI service instance (e.g., `mycompany-openai`)
- **Deployment**: A specific model deployed within your resource (e.g., `my-gpt4-deployment`)
- The deployment name is **user-defined** and often differs from the model name

**Example:**
```
Resource Name: mycompany-openai
Endpoint: https://mycompany-openai.openai.azure.com
Model: gpt-4
Deployment Name: production-gpt4  ← User-defined, not the same as model name!
```

## Configuration

### Environment Variables

Required variables for Azure OpenAI:

```bash
# .env

# Provider selection (REQUIRED)
MODEL_PROVIDER=azure

# Azure credentials (REQUIRED)
AZURE_API_KEY=your_azure_api_key_here
AZURE_ENDPOINT=https://your-resource.openai.azure.com

# Model configuration (REQUIRED)
MODEL=gpt-4

# Deployment configuration (OPTIONAL - defaults to MODEL if omitted)
AZURE_DEPLOYMENT_NAME=production-gpt4

# API version (OPTIONAL - uses default if omitted)
AZURE_API_VERSION=2024-02-15-preview

# Rate limits (OPTIONAL - defaults shown)
AZURE_RPM_LIMIT=100       # Requests per minute
AZURE_TPM_LIMIT=90000     # Tokens per minute
AZURE_DAILY_LIMIT=5000    # Requests per day
```

### Getting Your Azure Credentials

1. **Navigate to Azure Portal**: [https://portal.azure.com](https://portal.azure.com)
2. **Find Your Resource**: Search for your Azure OpenAI resource
3. **Get Endpoint**:
   - Go to resource overview
   - Copy the "Endpoint" URL (e.g., `https://mycompany-openai.openai.azure.com`)
4. **Get API Key**:
   - Navigate to "Keys and Endpoint" in the left sidebar
   - Copy either "KEY 1" or "KEY 2"
5. **Get Deployment Name**:
   - Navigate to "Model deployments" or "Deployments"
   - Copy the name of your deployed model (NOT the model type)

### Vault Configuration (Optional)

Create `.summarizer-config.yaml` in your vault root for per-model rate limits:

```yaml
out_folder: "Summaries"
max_links: 10
daily_notes_folder: "Journal"

# Per-model rate limits
model_limits:
  gpt-4:
    rpm_limit: 500
    tpm_limit: 150000
    daily_limit: 10000
  gpt-35-turbo:
    rpm_limit: 1000
    tpm_limit: 300000
    daily_limit: 20000
```

## Usage

### Basic Usage

```bash
# Process today's daily note
summarize-links from-note --vault ~/Notes

# Process specific date
summarize-links from-note --vault ~/Notes --date 2025-01-15

# Process all daily notes
summarize-links from-note --vault ~/Notes --all

# Check rate limit status
summarize-links status --vault ~/Notes
```

### Rate Limit Status

Azure rate limits are displayed in the status command:

```bash
$ summarize-links status --vault ~/Notes

Azure OpenAI Rate Limit Status
Model: gpt-4
Deployment: production-gpt4

       Current Usage
┏━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━┓
┃ Limit Type            ┃ Used ┃ Limit   ┃ Remaining ┃
┡━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━┩
│ Requests/Minute (RPM) │   45 │     100 │        55 │
│ Tokens/Minute (TPM)   │ 3500 │  90,000 │    86,500 │
│ Requests/Day          │  342 │   5,000 │     4,658 │
└───────────────────────┴──────┴─────────┴───────────┘
```

### Model Selection

Azure OpenAI supports various models. Common deployments:

- `gpt-4`: GPT-4 (8K context)
- `gpt-4-32k`: GPT-4 with 32K context
- `gpt-4-turbo`: GPT-4 Turbo (128K context)
- `gpt-35-turbo`: GPT-3.5 Turbo (16K context)
- `gpt-35-turbo-16k`: GPT-3.5 Turbo with 16K context

**Important**: Use your **deployment name**, not the model type:

```bash
# If your deployment is named "production-gpt4":
MODEL=gpt-4
AZURE_DEPLOYMENT_NAME=production-gpt4

# If your deployment name matches the model:
MODEL=gpt-4
# AZURE_DEPLOYMENT_NAME can be omitted (defaults to MODEL)
```

## Rate Limits

### Default Limits

The tool uses conservative default rate limits for Azure:

- **RPM**: 100 requests/minute
- **TPM**: 90,000 tokens/minute
- **Daily**: 5,000 requests/day

### Azure Quota Types

Azure OpenAI has two types of quotas:

1. **Quota Assigned to Deployment** (configured in Azure Portal):
   - Set per-deployment in your Azure resource
   - Varies by subscription and region
   - Check: Azure Portal → Your Resource → Quotas

2. **Token-Based Rate Limits**:
   - Measured in tokens per minute (TPM)
   - Different for each model
   - Applied at the deployment level

### Customizing Rate Limits

**Option 1: Environment Variables**

```bash
# .env
AZURE_RPM_LIMIT=500
AZURE_TPM_LIMIT=150000
AZURE_DAILY_LIMIT=10000
```

**Option 2: Vault Config (Per-Model)**

```yaml
# .summarizer-config.yaml
model_limits:
  gpt-4:
    rpm_limit: 500
    tpm_limit: 150000
    daily_limit: 10000
```

**Option 3: Check Your Azure Quotas**

1. Azure Portal → Your OpenAI Resource → Quotas
2. Note the TPM quota for your deployment
3. Set `AZURE_TPM_LIMIT` to match (or slightly below for safety margin)

## Troubleshooting

### Authentication Errors

**Error: "AZURE_API_KEY not set"**
- Solution: Add `AZURE_API_KEY` to your `.env` file
- Get key from: Azure Portal → Your Resource → Keys and Endpoint

**Error: "AZURE_ENDPOINT not set"**
- Solution: Add `AZURE_ENDPOINT` to your `.env` file
- Format: `https://your-resource-name.openai.azure.com`

**Error: "Authentication failed" (401)**
- Check: API key is correct and not expired
- Check: Azure subscription is active
- Try: Regenerate key in Azure Portal and update `.env`

**Error: "Access forbidden" (403)**
- Check: Your Azure subscription has access to Azure OpenAI
- Check: Resource is not disabled or suspended
- Check: You have proper RBAC permissions

### Deployment Errors

**Error: "Deployment 'xyz' not found" (404)**

Common causes:
1. **Wrong deployment name**: Check Azure Portal → Model deployments
2. **Case mismatch**: Deployment names are case-sensitive
3. **Wrong resource**: Verify `AZURE_ENDPOINT` points to correct resource

Solution:
```bash
# Find your actual deployment name in Azure Portal
# Azure Portal → Your Resource → Model deployments
# Copy the exact deployment name (case-sensitive)

AZURE_DEPLOYMENT_NAME=your-actual-deployment-name
```

**Deployment name vs Model name confusion:**

```bash
# WRONG - using model name when deployment is different
MODEL=gpt-4
AZURE_DEPLOYMENT_NAME=gpt-4  # ❌ This might not exist!

# RIGHT - using actual deployment name from Azure
MODEL=gpt-4
AZURE_DEPLOYMENT_NAME=production-gpt4  # ✅ Your actual deployment
```

### Endpoint Errors

**Error: "Azure endpoint must use HTTPS"**

- Your endpoint must start with `https://`
- Don't use `http://` (insecure, not supported by Azure)

Correct format:
```bash
# Good
AZURE_ENDPOINT=https://mycompany-openai.openai.azure.com

# Bad (missing https://)
AZURE_ENDPOINT=mycompany-openai.openai.azure.com

# Bad (http instead of https)
AZURE_ENDPOINT=http://mycompany-openai.openai.azure.com

# Bad (extra trailing slash or path)
AZURE_ENDPOINT=https://mycompany-openai.openai.azure.com/
AZURE_ENDPOINT=https://mycompany-openai.openai.azure.com/openai
```

### Rate Limit Errors

**Error: "Rate limit exceeded"**

The tool automatically handles rate limiting, but if you see this error:

1. **Check your Azure quotas**:
   - Azure Portal → Your Resource → Quotas
   - Compare with your `AZURE_*_LIMIT` settings

2. **Adjust limits in .env**:
   ```bash
   # Match your actual Azure quotas
   AZURE_RPM_LIMIT=60      # Requests per minute
   AZURE_TPM_LIMIT=40000   # Tokens per minute
   AZURE_DAILY_LIMIT=2000  # Requests per day
   ```

3. **Check usage**:
   ```bash
   summarize-links status --vault ~/Notes
   ```

4. **Request quota increase**:
   - Azure Portal → Your Resource → Quotas
   - Request quota increase (may require approval)

### JSON Response Format Errors

**Error: "System prompt must contain 'json'"**

This error occurs when using Azure's `json_object` response format without mentioning "json" in the system prompt.

**Solution:**
- This is a Langfuse prompt configuration issue
- Ensure your Langfuse system prompt mentions JSON output format
- Azure requires the word "json" in the system prompt for structured output

### Connection Errors

**Error: "Connection refused" or "Timeout"**

1. **Check endpoint URL**: Verify `AZURE_ENDPOINT` is correct
2. **Check network**: Ensure you can reach Azure (firewall, VPN, etc.)
3. **Check resource status**: Verify resource is not suspended in Azure Portal
4. **Check region**: Some regions may have intermittent connectivity

### API Version Errors

**Error: "API version not supported"**

If you see an API version error:

```bash
# Try using a different API version
AZURE_API_VERSION=2024-02-15-preview

# Or use a stable version
AZURE_API_VERSION=2023-12-01-preview
```

Check [Azure OpenAI API versions](https://learn.microsoft.com/en-us/azure/ai-services/openai/reference) for supported versions.

## Best Practices

### Security

1. **Never commit API keys**: Use `.env` files, keep out of git
2. **Rotate keys regularly**: Use Azure's key rotation features
3. **Use managed identities**: Consider Azure Managed Identities for production
4. **Restrict access**: Use Azure RBAC to limit who can access keys

### Cost Management

1. **Set rate limits**: Configure `AZURE_DAILY_LIMIT` to control costs
2. **Monitor usage**: Check `summarize-links status` regularly
3. **Use appropriate models**: GPT-3.5-turbo is cheaper than GPT-4
4. **Test with mock mode**: Use `--mock` for development to avoid API costs

### Performance

1. **Use local Ollama for dev**: Switch to Ollama for development/testing
2. **Batch processing**: Process multiple URLs in one command
3. **Appropriate rate limits**: Set limits slightly below Azure quotas
4. **Regional deployment**: Deploy Azure resource close to your location

### Reliability

1. **Implement error handling**: Tool automatically retries on failures
2. **Monitor quotas**: Keep an eye on Azure Portal quotas
3. **Use `--dry-run`**: Test commands before executing
4. **Enable verbose logging**: Use `--verbose` for debugging

## Comparison: Azure vs Gemini vs Ollama

| Feature | Azure OpenAI | Google Gemini | Ollama |
|---------|--------------|---------------|--------|
| **Cost** | Pay-per-use | Free tier + paid | Free (local) |
| **Privacy** | Enterprise-grade | Google Cloud | 100% local |
| **Speed** | Fast | Fast | Varies by hardware |
| **Models** | GPT-4, GPT-3.5 | Gemini 2.5, Flash | Llama, Mistral, etc. |
| **Quotas** | Configurable | 5-20 RPM (free) | Unlimited |
| **Setup** | Azure account | API key | Install Ollama |
| **Compliance** | GDPR, HIPAA, SOC2 | Google Cloud | N/A |
| **Offline** | No | No | Yes |

### When to Use Azure

**Choose Azure OpenAI when:**
- ✅ You need enterprise SLA guarantees
- ✅ You require specific compliance certifications
- ✅ You want data residency in specific regions
- ✅ You have an existing Azure subscription
- ✅ You need higher rate limits than Gemini free tier
- ✅ You want predictable pricing and billing through Azure

**Consider alternatives when:**
- ❌ You're on a tight budget (use Gemini free tier or Ollama)
- ❌ You need offline capability (use Ollama)
- ❌ You're prototyping/testing (use Gemini free tier or Ollama)
- ❌ You don't need enterprise features (Gemini or Ollama work fine)

## Additional Resources

- [Azure OpenAI Documentation](https://learn.microsoft.com/en-us/azure/ai-services/openai/)
- [Azure OpenAI Quotas and Limits](https://learn.microsoft.com/en-us/azure/ai-services/openai/quotas-limits)
- [Azure OpenAI Pricing](https://azure.microsoft.com/en-us/pricing/details/cognitive-services/openai-service/)
- [Azure OpenAI API Reference](https://learn.microsoft.com/en-us/azure/ai-services/openai/reference)
- [Azure Portal](https://portal.azure.com)

## Support

For Azure-specific issues:
1. Check Azure Service Health in Azure Portal
2. Review [Azure OpenAI documentation](https://learn.microsoft.com/en-us/azure/ai-services/openai/)
3. Contact Azure Support (if you have a support plan)

For tool-specific issues:
1. Check [main README](../README.md)
2. Enable verbose logging: `--verbose`
3. Open an issue on GitHub with logs and error messages
