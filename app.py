from flask import Flask, request, render_template, send_file
import geopandas as gpd
import wntr
import os
import tempfile
import zipfile
import io

# Inicializa a aplicação Flask
app = Flask(__name__)

# --- Coloque sua função convert_shp_to_inp aqui ---
# (A mesma função do seu script original, sem alterações)
def convert_shp_to_inp(zip_nodes_path, zip_links_path):
    """
    Converte shapefiles de nós e trechos para um arquivo EPANET .inp,
    aplicando as conversões de unidades necessárias.
    """
    try:
        # Cria diretórios temporários para extrair os arquivos
        with tempfile.TemporaryDirectory() as temp_dir_nodes, tempfile.TemporaryDirectory() as temp_dir_links:
            # Extrai os arquivos ZIP
            with zipfile.ZipFile(zip_nodes_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir_nodes)
            with zipfile.ZipFile(zip_links_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir_links)

            # Encontra os arquivos .shp dentro dos diretórios extraídos
            shapefile_nodes = next((os.path.join(temp_dir_nodes, f) for f in os.listdir(temp_dir_nodes) if f.endswith('.shp')), None)
            shapefile_links = next((os.path.join(temp_dir_links, f) for f in os.listdir(temp_dir_links) if f.endswith('.shp')), None)

            if not shapefile_nodes or not shapefile_links:
                raise FileNotFoundError("Não foi possível encontrar o arquivo .shp dentro de um dos arquivos ZIP.")

            # Leitura dos shapefiles
            nodes_gdf = gpd.read_file(shapefile_nodes)
            links_gdf = gpd.read_file(shapefile_links)

            # Inicializa a rede EPANET
            wn = wntr.network.WaterNetworkModel()

            # Dicionário para armazenar os nós
            nodes_dict = {}

            # Adiciona os nós a partir das coordenadas dos trechos
            for _, row in links_gdf.iterrows():
                start_point = row.geometry.coords[0]
                end_point = row.geometry.coords[-1]
                start_coords = (round(start_point[0], 6), round(start_point[1], 6))
                end_coords = (round(end_point[0], 6), round(end_point[1], 6))
                if start_coords not in nodes_dict:
                    node_id = f"N{len(nodes_dict) + 1}"
                    nodes_dict[start_coords] = node_id
                    wn.add_junction(node_id, base_demand=0, elevation=0, coordinates=start_coords)
                if end_coords not in nodes_dict:
                    node_id = f"N{len(nodes_dict) + 1}"
                    nodes_dict[end_coords] = node_id
                    wn.add_junction(node_id, base_demand=0, elevation=0, coordinates=end_coords)

            # Validação e atualização dos nós
            required_node_cols = {'Cota', 'Demanda'}
            if not required_node_cols.issubset(nodes_gdf.columns):
                 raise ValueError(f"O shapefile de nós deve conter as colunas: {', '.join(required_node_cols)}")
            for _, row in nodes_gdf.iterrows():
                coords = (round(row.geometry.x, 6), round(row.geometry.y, 6))
                node_id = nodes_dict.get(coords)
                if node_id:
                    junction = wn.get_node(node_id)
                    junction.elevation = row['Cota'] / 3.280839895054167
                    junction.demand_timeseries_list[0].base_value = row['Demanda'] / 15850.32314147994

            # Validação e adição dos trechos
            required_link_cols = {'Diametro', 'Extensao', 'Rugosidade'}
            if not required_link_cols.issubset(links_gdf.columns):
                 raise ValueError(f"O shapefile de trechos deve conter as colunas: {', '.join(required_link_cols)}")
            for _, row in links_gdf.iterrows():
                start_point = row.geometry.coords[0]
                end_point = row.geometry.coords[-1]
                start_coords = (round(start_point[0], 6), round(start_point[1], 6))
                end_coords = (round(end_point[0], 6), round(end_point[1], 6))
                node1 = nodes_dict[start_coords]
                node2 = nodes_dict[end_coords]
                link_id = f"P{len(wn.links) + 1}"
                diameter_m = row['Diametro'] / 39.37007874
                length_m = row['Extensao'] / 3.280839895032449
                wn.add_pipe(link_id, node1, node2,
                            length=length_m,
                            diameter=diameter_m,
                            roughness=row['Rugosidade'],
                            minor_loss=0.0)

            # Salva a rede em um arquivo .inp temporário
            with tempfile.NamedTemporaryFile(delete=False, mode='w+', suffix='.inp', encoding='utf-8') as temp_inp_file:
                output_inp_path = temp_inp_file.name
                wntr.network.write_inpfile(wn, output_inp_path)

            # Ajusta o arquivo .inp para garantir as unidades corretas
            with open(output_inp_path, 'r', encoding='utf-8') as file:
                data = file.readlines()
            options_index = -1
            clean_data = []
            for line in data:
                 stripped_line = line.strip().upper()
                 if stripped_line == '[OPTIONS]':
                      options_index = len(clean_data)
                 elif stripped_line.startswith(('UNITS', 'FLOWUNITS', 'HEADLOSS')):
                      continue
                 clean_data.append(line)
            if options_index != -1:
                options = ['Units               LPS\n', 'FlowUnits           LPS\n', 'Headloss            H-W\n']
                clean_data[options_index+1:options_index+1] = options
            
            final_inp_content = "".join(clean_data)
            os.remove(output_inp_path)
            return final_inp_content
    except Exception as e:
        # Retorna a mensagem de erro para ser exibida no site
        return f"Ocorreu um erro: {e}"

# Rota para a página inicial (GET) e para o processamento do formulário (POST)
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        # Verifica se os arquivos foram enviados
        if 'file_nodes' not in request.files or 'file_links' not in request.files:
            return "Erro: Faltando um ou mais arquivos.", 400
        
        file_nodes = request.files['file_nodes']
        file_links = request.files['file_links']

        # Verifica se os nomes dos arquivos não estão vazios
        if file_nodes.filename == '' or file_links.filename == '':
            return "Erro: Selecione os dois arquivos.", 400
        
        # Chama a função de conversão
        inp_content = convert_shp_to_inp(file_nodes, file_links)

        # Se o retorno for uma string de erro, exibe o erro
        if inp_content.startswith("Ocorreu um erro:"):
            return inp_content, 400

        # Se for sucesso, retorna o arquivo para download
        return send_file(
            io.BytesIO(inp_content.encode('utf-8')),
            mimetype='text/plain',
            as_attachment=True,
            download_name='modelo_convertido.inp'
        )

    # Se o método for GET, apenas renderiza a página HTML
    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True)