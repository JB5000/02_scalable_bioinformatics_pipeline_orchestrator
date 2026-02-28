#!/usr/bin/env nextflow

/**
 * Scalable Bioinformatics Pipeline
 * 
 * A production-grade Nextflow workflow for genomics data processing
 */

params.input = null
params.output = './results'
params.reference = null
params.memory = '8GB'
params.cpus = 4

// Input validation
if (!params.input) {
    println "ERROR: input parameter required"
    exit 1
}

// Create channels
input_files = Channel
    .fromPath(params.input)
    .ifEmpty { error "No input files found: ${params.input}" }

process validate_input {
    tag "$file"
    label 'small'
    
    input:
    file(file) from input_files
    
    output:
    file("validated_${file}") into validated_files
    
    script:
    """
    echo "Validating: $file"
    # Validation logic here
    cp $file validated_${file}
    """
}

process quality_control {
    tag "$sample"
    label 'medium'
    container 'biocontainers/fastqc:latest'
    
    input:
    file(sample) from validated_files
    
    output:
    file("*.html") into qc_results
    
    script:
    """
    fastqc $sample
    """
}

process alignment {
    tag "$sample"
    label 'large'
    container 'biocontainers/bwa:latest'
    
    input:
    file(sample) from validated_files
    file(ref) from file(params.reference)
    
    output:
    file("*.bam") into aligned_files
    
    script:
    """
    bwa mem -t ${task.cpus} $ref $sample > output.sam
    samtools view -b output.sam > aligned.bam
    """
}

process variant_calling {
    tag "$bam"
    label 'large'
    container 'biocontainers/gatk:latest'
    
    input:
    file(bam) from aligned_files
    
    output:
    file("*.vcf") into vcf_files
    
    script:
    """
    gatk HaplotypeCaller -I $bam -O variants.vcf
    """
}

workflow {
    quality_control(validated_files)
    alignment(validated_files, file(params.reference))
    variant_calling(aligned_files)
}
